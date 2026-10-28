from __future__ import annotations

import re
from typing import Annotated

from pydantic import BeforeValidator

_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_FULL = re.compile(r"(?:\d+(?:\.\d+)?(?:ms|h|m|s))+")


def parse_duration(value: object) -> float:
    """Parse ``30``, ``"30"``, ``"500ms"``, ``"2m"`` or ``"1m30s"`` into seconds."""
    if isinstance(value, bool):
        raise ValueError(f"invalid duration: {value!r}")
    if isinstance(value, int | float):
        seconds = float(value)
    elif isinstance(value, str):
        text = value.strip().replace(" ", "")
        try:
            seconds = float(text)
        except ValueError:
            if not _FULL.fullmatch(text):
                raise ValueError(
                    f"invalid duration: {value!r} (examples: 500ms, 30s, 2m, 1m30s)"
                ) from None
            seconds = sum(float(n) * _UNITS[unit] for n, unit in _PART.findall(text))
    else:
        raise ValueError(f"invalid duration: {value!r}")
    if seconds < 0:
        raise ValueError("duration must not be negative")
    return seconds


Duration = Annotated[float, BeforeValidator(parse_duration)]
