"""
Visualizer Node — giải thích kết quả và đề xuất biểu đồ.

Nâng cấp v2:
- Dùng with_structured_output(VisualizerOutput) thay vì parse text thủ công
- Robust fallback nếu LLM fail (rule-based chart detection giữ lại)
- @traced decorator
"""
import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.llm import get_llm
from src.agents.output_schemas import VisualizerOutput
from src.agents.prompts import VISUALIZER_SYSTEM_PROMPT
from src.agents.state import AgentState
from src.agents.tracing import record_llm_call, traced

logger = logging.getLogger(__name__)

SAMPLE_ROWS_FOR_LLM = 5  # Chỉ gửi 5 dòng mẫu cho LLM


def _build_default_chart(columns: list, results: list, user_query: str) -> dict:
    """Rule-based fallback chart detection."""
    x_axis = columns[0] if columns else ""
    series_keys = [
        c for c in columns[1:]
        if any(kw in c.lower() for kw in ["revenue", "total", "count", "quantity", "price", "avg", "sum"])
    ]
    if not series_keys and len(columns) > 1:
        series_keys = [columns[1]]

    chart_type = "table"
    if "date" in x_axis.lower() or "month" in x_axis.lower() or "year" in x_axis.lower():
        chart_type = "line"
    elif len(results) <= 7 and any(kw in x_axis.lower() for kw in ["gender", "payment", "method"]):
        chart_type = "pie"
    elif len(columns) >= 2 and series_keys:
        chart_type = "bar"

    return {
        "type": chart_type,
        "title": f"Biểu đồ: {user_query[:60]}",
        "xAxisKey": x_axis,
        "seriesKeys": series_keys,
    }


@traced("visualizer")
def visualizer_node(state: AgentState) -> AgentState:
    """
    Visualizer: sinh explanation tiếng Việt và chart config.
    
    Input state: execution_results, columns, user_query, generated_sql
    Output state: explanation, chart_config, status="completed"
    """
    results = state.get("execution_results")
    columns = state.get("columns", [])
    user_query = state.get("user_query", "")
    sql = state.get("generated_sql", "")

    if not results:
        state["explanation"] = "Không tìm thấy dữ liệu phù hợp với câu hỏi."
        state["chart_config"] = {"type": "table", "title": "Kết quả rỗng", "xAxisKey": "", "seriesKeys": []}
        state["status"] = "completed"
        return state

    default_chart = _build_default_chart(columns, results, user_query)
    sample_data = results[:SAMPLE_ROWS_FOR_LLM]

    # ── Call LLM with structured output ────────────────────────────────────
    try:
        llm = get_llm()
        structured_llm = llm.with_structured_output(VisualizerOutput)

        user_message = (
            f"Câu hỏi: {user_query}\n"
            f"SQL đã chạy: {sql}\n"
            f"Tổng số dòng: {len(results)}\n"
            f"Dữ liệu mẫu ({len(sample_data)} dòng đầu):\n"
            f"{json.dumps(sample_data, ensure_ascii=False, default=str)}"
        )

        result: VisualizerOutput = structured_llm.invoke([
            SystemMessage(content=VISUALIZER_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ])

        record_llm_call(
            state=state,
            node_name="visualizer",
            prompt_text=f"[SYSTEM]\n{VISUALIZER_SYSTEM_PROMPT}\n\n[USER]\n{user_message[:800]}",
            response_text=result.model_dump_json(),
            model=state.get("_llm_model", "gemini"),
        )

        state["explanation"] = result.explanation
        state["chart_config"] = result.chart_config.model_dump()
        logger.info(f"[Visualizer] Chart type: {result.chart_config.type}")

    except Exception as e:
        # Graceful fallback về rule-based chart
        logger.error(f"[Visualizer] LLM error, using fallback: {e}")
        state["explanation"] = f"Truy vấn thực thi thành công, trả về {len(results)} kết quả."
        state["chart_config"] = default_chart

    state["status"] = "completed"
    return state
