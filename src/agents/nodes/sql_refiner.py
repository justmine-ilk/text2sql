"""
SQL Refiner Node — sửa lỗi SQL dựa trên feedback từ Validator.

Nâng cấp v2:
- Dedicated Refiner prompt (không chỉ gọi lại Generator)
- Circuit breaker pattern (max 3 retries)
- @traced decorator
"""
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.llm import get_llm
from src.agents.nodes.sql_generator import _clean_sql
from src.agents.prompts import SQL_REFINER_SYSTEM_PROMPT, build_schema_context
from src.agents.state import AgentState
from src.agents.tools import get_schema_columns
from src.agents.tracing import record_llm_call, traced

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


@traced("sql_refiner")
def sql_refiner_node(state: AgentState) -> AgentState:
    """
    SQL Refiner: phân tích lỗi cụ thể và sửa lại SQL với prompt chuyên biệt.
    Circuit breaker sau MAX_RETRIES lần thất bại.
    
    Input state: generated_sql, validator_feedback, retry_count
    Output state: generated_sql (fixed), retry_count++
    """
    retry_count = state.get("retry_count", 0)

    # ── Circuit breaker ─────────────────────────────────────────────────────
    if retry_count >= MAX_RETRIES:
        logger.warning(f"[SQL Refiner] Max retries ({MAX_RETRIES}) reached — giving up.")
        state["status"] = "failed"
        state["execution_error"] = (
            f"Hệ thống đã thử {MAX_RETRIES} lần nhưng không tạo được SQL hợp lệ. "
            "Vui lòng thử lại với câu hỏi rõ ràng hơn."
        )
        return state

    # ── Build refiner-specific prompt ──────────────────────────────────────
    schema_columns = get_schema_columns()
    schema_context = build_schema_context(schema_columns)

    failed_sql = state.get("generated_sql", "")
    validator_feedback = state.get("validator_feedback", "")
    user_query = state.get("user_query", "")

    system_prompt = SQL_REFINER_SYSTEM_PROMPT.format(
        user_query=user_query,
        failed_sql=failed_sql,
        validator_feedback=validator_feedback,
        schema_context=schema_context,
    )

    user_message = (
        f"Hãy phân tích lỗi cụ thể và tạo lại câu SQL ĐÚNG.\n"
        f"Câu hỏi gốc: {user_query}\n"
        f"Lỗi cần sửa: {validator_feedback}"
    )

    # ── Call LLM với dedicated refiner prompt ──────────────────────────────
    try:
        llm = get_llm()
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ])

        raw_sql = response.content
        fixed_sql = _clean_sql(raw_sql)

        record_llm_call(
            state=state,
            node_name="sql_refiner",
            prompt_text=f"[SYSTEM]\n{system_prompt[:1000]}\n\n[USER]\n{user_message}",
            response_text=raw_sql[:500],
            model=state.get("_llm_model", "gemini"),
        )

        state["generated_sql"] = fixed_sql
        state["retry_count"] = retry_count + 1
        state["validator_feedback"] = None  # Reset feedback for next validation

        logger.info(
            f"[SQL Refiner] Retry {retry_count + 1}/{MAX_RETRIES} — "
            f"Fixed SQL: {fixed_sql[:80]}..."
        )

    except Exception as e:
        logger.error(f"[SQL Refiner] LLM error: {e}")
        state["retry_count"] = retry_count + 1

    return state
