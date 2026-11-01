from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .duration import Duration

_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RequestSpec(_Model):
    method: str = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)
    json_body: Any = Field(default=None, alias="json")
    body: str | None = None
    timeout: Duration = 30.0
    follow_redirects: bool = True

    @field_validator("method")
    @classmethod
    def _method(cls, v: str) -> str:
        v = v.upper()
        if v not in _METHODS:
            raise ValueError(f"unsupported method {v!r}")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("timeout")
    @classmethod
    def _timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("timeout must be greater than 0")
        return v

    @model_validator(mode="after")
    def _one_body(self) -> RequestSpec:
        if self.json_body is not None and self.body is not None:
            raise ValueError("use either 'json' or 'body', not both")
        return self


class Step(_Model):
    name: str = ""
    request: RequestSpec


class Stage(_Model):
    duration: Duration
    target: float = Field(ge=0)

    @field_validator("duration")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("stage duration must be greater than 0")
        return v


class LoadSpec(_Model):
    """How much load to apply over time.

    ``mode="vus"``: closed model, ``target`` is the number of virtual users.
    ``mode="rate"``: open model, ``target`` is iterations started per second.
    Either give ``stages`` or the shorthand ``vus``/``rate`` + ``duration``.
    """

    mode: Literal["vus", "rate"] = "vus"
    vus: int | None = Field(default=None, ge=0)
    rate: float | None = Field(default=None, ge=0)
    duration: Duration | None = None
    start: float | None = Field(default=None, ge=0)
    stages: list[Stage] = Field(default_factory=list)
    max_in_flight: int = Field(default=1000, ge=1)
    graceful_stop: Duration = 10.0

    @model_validator(mode="before")
    @classmethod
    def _infer_mode(cls, data: Any) -> Any:
        if isinstance(data, dict) and "mode" not in data and data.get("rate") is not None:
            data = {**data, "mode": "rate"}
        return data

    @model_validator(mode="after")
    def _expand_shorthand(self) -> LoadSpec:
        if self.mode == "vus" and self.rate is not None:
            raise ValueError("'rate' cannot be used with mode 'vus'")
        if self.mode == "rate" and self.vus is not None:
            raise ValueError("'vus' cannot be used with mode 'rate'")
        level = self.vus if self.mode == "vus" else self.rate
        if self.stages:
            if level is not None or self.duration is not None:
                raise ValueError("use either 'stages' or 'vus'/'rate' + 'duration', not both")
            return self
        if level is None or self.duration is None:
            field = "vus" if self.mode == "vus" else "rate"
            raise ValueError(f"set 'stages', or set both '{field}' and 'duration'")
        if self.duration <= 0:
            raise ValueError("duration must be greater than 0")
        self.stages = [Stage(duration=self.duration, target=float(level))]
        if self.start is None:
            self.start = float(level)
        return self

    @property
    def total_duration(self) -> float:
        return sum(s.duration for s in self.stages)

    @property
    def peak(self) -> float:
        return max([self.start or 0.0, *(s.target for s in self.stages)])

    def target_at(self, t: float) -> float:
        """Target level at ``t`` seconds into the run (linear ramp within each stage)."""
        prev = self.start if self.start is not None else 0.0
        elapsed = 0.0
        for stage in self.stages:
            if t < elapsed + stage.duration:
                frac = max(0.0, t - elapsed) / stage.duration
                return prev + (stage.target - prev) * frac
            elapsed += stage.duration
            prev = stage.target
        return prev


class Limits(_Model):
    """Server-wide safety caps, so a typo can't flood a target."""

    max_vus: int = Field(default=1000, ge=1, le=1_000_000)
    max_rate: float = Field(default=5000.0, gt=0, le=10_000_000)
    max_duration: Duration = 7200.0

    @field_validator("max_duration")
    @classmethod
    def _positive_duration(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("max_duration must be greater than 0")
        return v

    def target_error(self, mode: str, value: float) -> str | None:
        if mode == "vus" and value > self.max_vus:
            return f"{value:g} virtual users is over the limit of {self.max_vus:g} (see Settings)"
        if mode == "rate" and value > self.max_rate:
            return f"{value:g} requests/s is over the limit of {self.max_rate:g} (see Settings)"
        return None

    def plan_errors(self, plan: TestPlan) -> list[str]:
        errors = []
        if (e := self.target_error(plan.load.mode, plan.load.peak)) is not None:
            errors.append(e)
        if plan.load.total_duration > self.max_duration:
            errors.append(
                f"duration of {plan.load.total_duration:g}s is over the limit of "
                f"{self.max_duration:g}s (see Settings)"
            )
        return errors


class TestPlan(_Model):
    __test__ = False  # keep pytest from collecting this class

    name: str = "untitled"
    steps: list[Step] = Field(min_length=1)
    load: LoadSpec
    warmup: Duration = 0.0
    insecure: bool = False

    @model_validator(mode="before")
    @classmethod
    def _single_request_shorthand(cls, data: Any) -> Any:
        if isinstance(data, dict) and "request" in data:
            if "steps" in data:
                raise ValueError("use either 'request' or 'steps', not both")
            request = data["request"]
            data = {k: v for k, v in data.items() if k != "request"}
            data["steps"] = [{"name": "request", "request": request}]
        return data

    @model_validator(mode="after")
    def _step_names(self) -> TestPlan:
        seen: set[str] = set()
        for i, step in enumerate(self.steps, start=1):
            if not step.name:
                step.name = f"step-{i}"
            if step.name in seen:
                raise ValueError(f"duplicate step name {step.name!r}")
            seen.add(step.name)
        return self

    @classmethod
    def from_yaml(cls, text: str) -> TestPlan:
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError("test file must be a YAML mapping")
        return cls.model_validate(data)

    @classmethod
    def from_file(cls, path: str | Path) -> TestPlan:
        return cls.from_yaml(Path(path).read_text(encoding="utf-8"))
