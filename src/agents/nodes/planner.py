"""
Planner Node — Phân tích intent và phát hiện câu hỏi mơ hồ.

Nâng cấp v2:
- Dùng with_structured_output(PlannerOutput) thay vì parse text thủ công
- Dynamic schema context từ DB
- Conversation memory support
- @traced decorator
- Typed error handling
"""
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.errors import LLMError, LLMParseError
from src.agents.llm import get_llm
from src.agents.output_schemas import PlannerOutput
from src.agents.prompts import (
    PLANNER_SYSTEM_PROMPT,
    build_conversation_context,
    build_schema_context,
)
from src.agents.state import AgentState
from src.agents.tools import get_schema_columns
from src.agents.tracing import record_llm_call, traced

logger = logging.getLogger(__name__)


@traced("planner")
def planner_node(state: AgentState) -> AgentState:
    """
    Planner Agent: phân tích câu hỏi, phát hiện mơ hồ, xác định intent.
    
    Input state: user_query, conversation_history
    Output state: is_ambiguous, clarification_question, intent_summary, 
                  relevant_columns, query_complexity
    """
    user_query = state.get("user_query", "").strip()

    # ── Rule-based quick check: cực ngắn → chắc chắn mơ hồ ────────────────
    words = [w for w in user_query.split() if len(w) > 1]
    if len(words) < 3:
        state["is_ambiguous"] = True
        state["clarification_question"] = (
            f"Câu hỏi '{user_query}' quá ngắn để phân tích. "
            "Bạn muốn xem dữ liệu theo danh mục, sản phẩm, thành phố hay khoảng thời gian nào?"
        )
        state["intent_summary"] = "Unknown — cần làm rõ"
        state["relevant_columns"] = []
        state["query_complexity"] = "simple"
        state["status"] = "need_clarification"
        logger.info(f"[Planner] Quick reject — too short: '{user_query}'")
        return state

    # ── Build dynamic context ───────────────────────────────────────────────
    schema_columns = get_schema_columns()
    schema_context = build_schema_context(schema_columns)
    conversation_context = build_conversation_context(
        state.get("conversation_history", [])
    )

    system_prompt = PLANNER_SYSTEM_PROMPT.format(schema_context=schema_context)

    user_message = (
        f"{conversation_context}\n\n"
        f"Câu hỏi hiện tại: {user_query}"
    )

    # ── Call LLM with structured output ────────────────────────────────────
    try:
        llm = get_llm()
        structured_llm = llm.with_structured_output(PlannerOutput)

        result: PlannerOutput = structured_llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ])

        # Record LLM call for tracing
        record_llm_call(
            state=state,
            node_name="planner",
            prompt_text=f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_message}",
            response_text=result.model_dump_json(),
            model=state.get("_llm_model", "gemini"),
        )

        # ── Update state ────────────────────────────────────────────────────
        state["is_ambiguous"] = result.is_ambiguous
        state["clarification_question"] = result.clarification_question
        state["intent_summary"] = result.intent_summary
        state["relevant_columns"] = result.relevant_columns or []
        state["query_complexity"] = result.complexity

        if result.is_ambiguous:
            state["status"] = "need_clarification"
            logger.info(f"[Planner] Ambiguous query detected: '{user_query}'")
        else:
            logger.info(f"[Planner] Intent: {result.intent_summary} | Complexity: {result.complexity}")

    except Exception as e:
        # Graceful fallback — không crash, tiếp tục với defaults
        logger.error(f"[Planner] LLM error: {e}")
        state["is_ambiguous"] = False
        state["intent_summary"] = "General SQL Query"
        state["relevant_columns"] = []
        state["query_complexity"] = "medium"

    return state
