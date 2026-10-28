from pathlib import Path

import pytest
from pydantic import ValidationError

from loadpilot.config import TestPlan, parse_duration


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (30, 30.0),
        (1.5, 1.5),
        ("45", 45.0),
        ("500ms", 0.5),
        ("2m", 120.0),
        ("1h", 3600.0),
        ("1m30s", 90.0),
        (" 10s ", 10.0),
    ],
)
def test_parse_duration(value, expected):
    assert parse_duration(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", ["", "abc", "10x", "-5", -1, True, None, "5 minutes"])
def test_parse_duration_rejects(value):
    with pytest.raises(ValueError):
        parse_duration(value)


def test_shorthand_vus_becomes_flat_stage():
    plan = TestPlan.model_validate(
        {"request": {"url": "http://x/"}, "load": {"vus": 5, "duration": "10s"}}
    )
    assert plan.load.mode == "vus"
    assert plan.load.total_duration == 10
    assert plan.load.target_at(0) == 5
    assert plan.load.target_at(9.9) == 5
    assert plan.steps[0].name == "request"
    assert plan.steps[0].request.method == "GET"


def test_rate_shorthand_infers_mode():
    plan = TestPlan.model_validate(
        {"request": {"url": "http://x/"}, "load": {"rate": 100, "duration": 5}}
    )
    assert plan.load.mode == "rate"
    assert plan.load.target_at(2) == 100


def test_stages_ramp_linearly():
    plan = TestPlan.model_validate(
        {
            "request": {"url": "http://x/"},
            "load": {
                "stages": [
                    {"duration": "10s", "target": 10},
                    {"duration": "5s", "target": 10},
                    {"duration": "5s", "target": 0},
                ]
            },
        }
    )
    load = plan.load
    assert load.total_duration == 20
    assert load.target_at(0) == 0
    assert load.target_at(5) == pytest.approx(5)
    assert load.target_at(12) == 10
    assert load.target_at(17.5) == pytest.approx(5)
    assert load.target_at(100) == 0


def test_yaml_with_steps_and_default_names():
    plan = TestPlan.from_yaml(
        """
name: two-steps
load: {vus: 2, duration: 1s}
steps:
  - request: {url: "http://x/a"}
  - name: create
    request: {method: post, url: "http://x/b", json: {a: 1}}
"""
    )
    assert [s.name for s in plan.steps] == ["step-1", "create"]
    assert plan.steps[1].request.method == "POST"
    assert plan.steps[1].request.json_body == {"a": 1}


EXAMPLES = sorted((Path(__file__).parents[2] / "examples").glob("*.yaml"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_are_valid(path):
    assert TestPlan.from_file(path).load.total_duration > 0


def test_examples_exist():
    assert EXAMPLES


@pytest.mark.parametrize(
    "data",
    [
        {"request": {"url": "ftp://x"}, "load": {"vus": 1, "duration": 1}},
        {"request": {"url": "http://x", "method": "BREW"}, "load": {"vus": 1, "duration": 1}},
        {
            "request": {"url": "http://x", "json": {}, "body": "a"},
            "load": {"vus": 1, "duration": 1},
        },
        {"request": {"url": "http://x"}, "load": {"vus": 1}},
        {"request": {"url": "http://x"}, "load": {"vus": 1, "rate": 5, "duration": 1}},
        {
            "request": {"url": "http://x"},
            "load": {"vus": 1, "duration": 1, "stages": [{"duration": 1, "target": 1}]},
        },
        {"request": {"url": "http://x"}, "load": {"vus": 1, "duration": 0}},
        {"request": {"url": "http://x"}, "load": {"vus": 1, "duration": 1}, "typo": 1},
        {
            "steps": [
                {"name": "a", "request": {"url": "http://x"}},
                {"name": "a", "request": {"url": "http://x"}},
            ],
            "load": {"vus": 1, "duration": 1},
        },
        {"steps": [], "load": {"vus": 1, "duration": 1}},
    ],
)
def test_invalid_plans(data):
    with pytest.raises(ValidationError):
        TestPlan.model_validate(data)
