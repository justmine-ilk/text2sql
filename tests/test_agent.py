import pytest
from src.agents.tools import _validate_sql_internal
from src.agents.output_schemas import PlannerOutput, VisualizerOutput

def test_sql_validation_tool():
    # Valid SELECT
    res1 = _validate_sql_internal("SELECT category_name, SUM(quantity * price) FROM online_retail GROUP BY category_name;")
    assert res1.is_valid is True
    assert res1.is_safe is True

    # Dangerous DDL/DML keyword
    res2 = _validate_sql_internal("DROP TABLE online_retail;")
    assert res2.is_valid is False
    assert res2.is_safe is False
    assert "bị cấm" in res2.error_message

    # Syntax Error
    res3 = _validate_sql_internal("SELECT FROM WHERE WHERE;")
    assert res3.is_valid is False
    assert "SQLite" in res3.error_message or "cú pháp" in res3.error_message


def test_output_schemas():
    p = PlannerOutput(
        is_ambiguous=False,
        intent_summary="Aggregation",
        relevant_columns=["category_name", "price"]
    )
    assert p.is_ambiguous is False
    assert p.complexity == "medium"
