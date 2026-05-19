import pytest

from services.deadlines_auto_creator import _extract_days_from_text, _validate_days_value


@pytest.mark.parametrize(
    "text, expected",
    [
        ("appeal within 15 days", 15),
        ("file appeal in 7 days", 7),
        ("notice of appeal within 30 days", 30),
        ("30 days to file appeal", 30),
        ("challenge within 21 days", 21),
        ("Cost is 500 Rs, appeal in 30 days", 30),
        ("appeal within 30 day.", 30),
        ("file appeal within 30 business days", 30),
        ("appeal within 21 calendar days", 21),
        ("appeal in about 7 days", 7),
        ("notice of appeal within 15, days", 15),
    ],
)
def test_extract_days_from_text_variants(text, expected):
    assert _extract_days_from_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "Invalid text",
        "appeal by tomorrow",
        "30 days",
        "30days",
        "30 Days",
        "within 21 days of service",
        "payment due in 30 days",
        "file payment in 30 days",
        "30 business days",
        "21 calendar days",
        "in about 7 days",
    ],
)
def test_extract_days_from_text_invalid_inputs(text):
    assert _extract_days_from_text(text) is None


@pytest.mark.parametrize(
    "days, expected",
    [(1, True), (365, True), (0, False), (366, False)],
)
def test_validate_days_value_bounds(days, expected):
    assert _validate_days_value(days) is expected
