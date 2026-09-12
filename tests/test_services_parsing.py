import pytest

from app.services import _parse_currency, _parse_date, _parse_quantity, _row_is_blank


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("100.50", 100.50),
        ("$1,200.50", 1200.50),
        ("1,200.50", 1200.50),
        (" 42.00 ", 42.00),
        ("(15.00)", -15.00),
        ("not_a_number", None),
        ("N/A", None),
        ("", None),
    ],
)
def test_parse_currency(raw, expected):
    assert _parse_currency(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("10", 10),
        ("1,200", 1200),
        ("10.0", 10),
        ("10.5", None),
        ("ten", None),
        ("N/A", None),
        ("-1", -1),
    ],
)
def test_parse_quantity(raw, expected):
    assert _parse_quantity(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-08-01", "2026-08-01"),
        ("08/01/2026", "2026-08-01"),
        ("08-01-2026", "2026-08-01"),
        ("August 1, 2026", "2026-08-01"),
        ("Aug 1, 2026", "2026-08-01"),
        ("2026/13/40", None),
        ("not a date", None),
    ],
)
def test_parse_date(raw, expected):
    assert _parse_date(raw) == expected


def test_row_is_blank_true_when_all_fields_blank():
    row = {"a": "", "b": None, "c": "   "}
    assert _row_is_blank(row, ["a", "b", "c"]) is True


def test_row_is_blank_false_when_any_field_has_content():
    row = {"a": "", "b": "x", "c": None}
    assert _row_is_blank(row, ["a", "b", "c"]) is False
