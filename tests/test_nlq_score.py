"""Tests for the DL-026 scoring rules."""
import datetime as dt
from decimal import Decimal

from nlq.score import matches

D = dt.date


def test_extra_columns_and_column_order_are_ignored():
    ref = [("Turkana",), ("Wajir",)]
    gen = [(0.9, "Wajir", "KE008"), (0.8, "Turkana", "KE023")]
    assert matches(ref, gen)


def test_rows_must_match_as_whole_rows_not_column_by_column():
    ref = [("Turkana", 0.9), ("Wajir", 0.8)]
    swapped = [("Turkana", 0.8), ("Wajir", 0.9)]   # same column values, wrong pairing
    assert not matches(ref, swapped)


def test_numbers_rounded_to_2_decimals_and_types_ignored():
    assert matches([(Decimal("0.39865"),)], [(0.4,)])
    assert not matches([(Decimal("0.39865"),)], [(0.41,)])
    assert matches([(47,)], [(Decimal("47"),)])


def test_share_and_percentage_count_as_equal_both_ways():
    assert matches([(Decimal("0.2534"),)], [(25.34,)])
    assert matches([(25.34,)], [(0.2534,)])


def test_scaling_never_collapses_small_numbers():
    # Regression: dividing by 100 before rounding made 0.28 -> 0.00 match a correlation of -0.0009.
    assert not matches([(Decimal("0.2784"),)], [(-0.0009,)])
    assert not matches([(-0.0009,)], [(Decimal("0.2784"),)])


def test_order_matters_only_when_ordered():
    ref = [("A",), ("B",)]
    assert matches(ref, [("B",), ("A",)], ordered=False)
    assert not matches(ref, [("B",), ("A",)], ordered=True)


def test_row_count_and_missing_columns_fail():
    assert not matches([("A",), ("B",)], [("A",)])
    assert not matches([("A", 1)], [("A",)])


def test_dates_compare_with_datetimes_at_midnight_and_strings():
    assert matches([(D(2026, 9, 1),)], [(dt.datetime(2026, 9, 1),)])
    assert matches([(D(2026, 9, 1),)], [("2026-09-01",)])


def test_empty_results_match_only_empty_results():
    assert matches([], [])
    assert not matches([], [("A",)])


def test_duplicates_count():
    assert not matches([("A",), ("A",)], [("A",), ("B",)])
