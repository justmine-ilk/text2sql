"""
SQL Validator Node — kiểm tra SQL an toàn và hợp lệ.

Nâng cấp v2:
- Dùng _validate_sql_internal() từ tools.py (DRY)
- Cost estimation thực tế từ EXPLAIN QUERY PLAN
- @traced decorator
"""
import logging

from src.agents.state import AgentState
from src.agents.tools import _validate_sql_internal
from src.agents.tracing import traced

logger = logging.getLogger(__name__)


@traced("sql_validator")
def sql_validator_node(state: AgentState) -> AgentState:
    """
    SQL Validator: kiểm tra SQL có an toàn và hợp lệ không.
    
    Input state: generated_sql
    Output state: is_valid_sql, is_safe, validator_feedback, 
                  estimated_bytes, estimated_rows, cost_warning_level, safety_warning
    """
    sql = state.get("generated_sql", "").strip()

    result = _validate_sql_internal(sql)

    state["is_valid_sql"] = result.is_valid
    state["is_safe"] = result.is_safe
    state["validator_feedback"] = result.error_message
    state["safety_warning"] = result.safety_warning
    state["estimated_bytes"] = result.estimated_bytes
    state["cost_warning_level"] = result.warning_level

    # Sync generated_sql with LIMIT-appended version if needed
    if result.is_valid and sql and "LIMIT" not in sql.upper():
        state["generated_sql"] = sql.rstrip(";") + " LIMIT 1000;"

    if result.is_valid:
        logger.info(
            f"[SQL Validator] VALID — estimated {result.estimated_bytes:,} bytes "
            f"({result.warning_level})"
        )
    else:
        logger.warning(f"[SQL Validator] INVALID — {result.error_message}")

    return state
