"""
SQL Generator Node — sinh SQL từ câu hỏi tự nhiên.

Nâng cấp v2:
- Dynamic schema injection từ DB (không hardcode)
- Semantic few-shot search (keyword matching)
- Conversation memory
- Feedback-driven retry với dedicated prompt context
- @traced decorator
- Clean SQL extraction (không split("```sql"))
"""
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.llm import get_llm
from src.agents.prompts import (
    SQL_GENERATOR_SYSTEM_PROMPT,
    build_conversation_context,
    build_feedback_context,
    build_few_shot_context,
    build_schema_context,
)
from src.agents.state import AgentState
from src.agents.tools import get_relevant_few_shots, get_schema_columns
from src.agents.tracing import record_llm_call, traced

logger = logging.getLogger(__name__)


def _clean_sql(raw: str) -> str:
    """
    Trích xuất SQL thuần từ output LLM (handle markdown code blocks).
    Robust hơn split("```sql") — handle nhiều format khác nhau.
    """
    raw = raw.strip()

    # Remove markdown code fences
    patterns = [
        r"```sql\s*([\s\S]+?)\s*```",
        r"```\s*([\s\S]+?)\s*```",
        r"`(SELECT[\s\S]+?)`",
    ]
    for pat in patterns:
        match = re.search(pat, raw, re.IGNORECASE)
        if match:
            raw = match.group(1).strip()
            break

    # Remove leading/trailing whitespace and common prefixes
    for prefix in ["SQL:", "Câu SQL:", "Truy vấn:", "Query:"]:
        if raw.upper().startswith(prefix.upper()):
            raw = raw[len(prefix):].strip()

    # Ensure ends with semicolon
    if raw and not raw.endswith(";"):
        raw += ";"

    return raw


@traced("sql_generator")
def sql_generator_node(state: AgentState) -> AgentState:
    """
    SQL Generator: dùng LLM sinh SQL từ câu hỏi tự nhiên.
    
    Input state: user_query, intent_summary, validator_feedback (on retry),
                 conversation_history, relevant_columns
    Output state: generated_sql
    """
    user_query = state.get("user_query", "")
    validator_feedback = state.get("validator_feedback")
    previous_sql = state.get("generated_sql")
    retry_count = state.get("retry_count", 0)

    # ── Build dynamic context ───────────────────────────────────────────────
    schema_columns = get_schema_columns()
    schema_context = build_schema_context(schema_columns)

    # Semantic few-shot search based on current query
    relevant_examples = get_relevant_few_shots(user_query, top_k=3)
    few_shot_context = build_few_shot_context(relevant_examples)

    conversation_context = build_conversation_context(
        state.get("conversation_history", [])
    )
    feedback_context = build_feedback_context(validator_feedback, previous_sql)

    # Build system prompt with all dynamic contexts
    system_prompt = SQL_GENERATOR_SYSTEM_PROMPT.format(
        schema_context=schema_context,
        few_shot_context=few_shot_context,
        conversation_context=conversation_context,
        feedback_context=feedback_context,
    )

    # Add intent context to user message
    intent = state.get("intent_summary", "")
    relevant_cols = state.get("relevant_columns", [])
    
    user_message = f"Câu hỏi: {user_query}"
    if intent:
        user_message += f"\nPhân tích intent: {intent}"
    if relevant_cols:
        user_message += f"\nCột liên quan: {', '.join(relevant_cols)}"
    if retry_count > 0:
        user_message += f"\n[Lần thử thứ {retry_count + 1} — hãy sửa lỗi từ lần trước]"

    # ── Call LLM ────────────────────────────────────────────────────────────
    try:
        llm = get_llm()
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ])

        raw_sql = response.content
        sql = _clean_sql(raw_sql)

        # Record for tracing
        record_llm_call(
            state=state,
            node_name="sql_generator",
            prompt_text=f"[SYSTEM]\n{system_prompt[:1500]}\n\n[USER]\n{user_message}",
            response_text=raw_sql[:500],
            model=state.get("_llm_model", "gemini"),
        )

        logger.info(f"[SQL Generator] Generated (retry={retry_count}): {sql[:100]}...")
        state["generated_sql"] = sql

    except Exception as e:
        logger.error(f"[SQL Generator] LLM error (retry={retry_count}): {e}")
        # Fallback SQL tổng quát, không crash
        state["generated_sql"] = "SELECT * FROM online_retail LIMIT 10;"

    return state
