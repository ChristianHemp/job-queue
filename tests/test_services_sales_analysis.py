import pytest

from app.schemas import SalesDataPayload
from app.services import execute_analyze_sales_data

TEST_DATA_DIR = "test_data"


def test_clean_data_totals_and_no_issues():
    result = execute_analyze_sales_data(SalesDataPayload(file_path=f"{TEST_DATA_DIR}/test_sales_data.csv"))

    assert result["row_count"] == 16
    assert result["processed_row_count"] == 16
    assert result["issues"] == {}
    assert result["total_revenue"] == pytest.approx(16735.00)
    assert result["total_quantity"] == 174
    # Spot-check one category aggregation, not just the grand total.
    assert result["revenue_by_category"]["Electronics"] == pytest.approx(7405.00)


def test_dirty_data_parses_edge_cases_and_tallies_issues():
    result = execute_analyze_sales_data(SalesDataPayload(file_path=f"{TEST_DATA_DIR}/dirty_sales_data.csv"))

    assert result["row_count"] == 22
    assert result["processed_row_count"] == 21
    assert result["issues"] == {
        "missing_revenue": 1,
        "missing_quantity": 1,
        "unparseable_revenue": 1,
        "unparseable_quantity": 3,
        "unparseable_date": 1,
        "blank_row": 1,
    }
    assert result["total_revenue"] == pytest.approx(4412.96)
    assert result["total_quantity"] == 93


def test_ambiguous_headers_raises_value_error():
    with pytest.raises(ValueError, match="Ambiguous column mapping"):
        execute_analyze_sales_data(
            SalesDataPayload(file_path=f"{TEST_DATA_DIR}/ambiguous_headers_sales_data.csv")
        )


def test_large_file_shape_sanity_check():
    result = execute_analyze_sales_data(SalesDataPayload(file_path=f"{TEST_DATA_DIR}/sales_data_large.csv"))

    assert result["row_count"] == 600
    assert result["processed_row_count"] <= 600
    assert result["total_revenue"] > 0
    assert result["total_quantity"] > 0
