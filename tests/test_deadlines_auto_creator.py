import pytest

from services.deadlines_auto_creator import _extract_days_from_text, _validate_days_value


@pytest.mark.parametrize(
    "text, expected",
    [
        ("30 days", 30),
        ("appeal within 15 days", 15),
        ("file appeal in 7 days", 7),
        ("30days", 30),
        ("30 Days", 30),
        ("Cost is 500 Rs, appeal in 30 days", 30),
        ("within 21 days of service", 21),
    ],
)
def test_extract_days_from_text_variants(text, expected):
    assert _extract_days_from_text(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", None, "Invalid text", "appeal by tomorrow"],
)
def test_extract_days_from_text_invalid_inputs(text):
    assert _extract_days_from_text(text) is None


@pytest.mark.parametrize(
    "days, expected",
    [(1, True), (365, True), (0, False), (366, False)],
)
def test_validate_days_value_bounds(days, expected):
    assert _validate_days_value(days) is expected
