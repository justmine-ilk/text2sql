"""
Agent Tracing & Observability System — lấy cảm hứng từ OpenCode's OpenTelemetry.

Ghi nhận toàn bộ input/output/timing/tokens của mỗi agent node.
Cho phép debug, review, và chấm điểm từng lượt chạy agent.
"""
import functools
import time
import json
import uuid
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agents.errors import TracingError

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────

@dataclass
class NodeTrace:
    """Trace cho một node trong agent workflow."""
    node_name: str
    start_time: str                     # ISO format
    end_time: str = ""
    duration_ms: float = 0.0

    # LLM interaction
    llm_model: str = ""
    llm_prompt_text: str = ""           # Full system + user prompt
    llm_response_text: str = ""         # Full LLM response
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0

    # Tool calls (function calling)
    tool_calls: List[dict] = field(default_factory=list)

    # State changes
    input_snapshot: dict = field(default_factory=dict)  # State trước khi node chạy
    output_changes: dict = field(default_factory=dict)  # Những gì node thay đổi trong state

    # Status
    error: Optional[str] = None
    retry_count: int = 0
    status: str = "success"  # "success", "error", "skipped"


@dataclass
class AgentTrace:
    """Trace cho toàn bộ một lượt chạy agent (từ user query → final result)."""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    thread_id: str = ""
    user_query: str = ""
    user_id: str = "anonymous"

    nodes: List[NodeTrace] = field(default_factory=list)

    # Aggregated metrics
    total_duration_ms: float = 0.0
    total_llm_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tool_calls: int = 0

    # Final result
    final_status: str = ""
    final_sql: Optional[str] = None
    final_row_count: int = 0

    # Scoring (populated by eval or manual review)
    score: Optional[float] = None
    score_breakdown: Optional[dict] = None

    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def add_node(self, node: NodeTrace):
        """Add a node trace và cập nhật aggregate metrics."""
        self.nodes.append(node)
        self.total_duration_ms += node.duration_ms
        self.total_prompt_tokens += node.llm_prompt_tokens
        self.total_completion_tokens += node.llm_completion_tokens
        self.total_tool_calls += len(node.tool_calls)
        if node.llm_prompt_text or node.llm_response_text:
            self.total_llm_calls += 1

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


# ─────────────────────────────────────────────
# State keys tracked per node
# ─────────────────────────────────────────────

NODE_TRACKED_INPUT_KEYS = {
    "planner": ["user_query", "conversation_history"],
    "sql_generator": ["user_query", "intent_summary", "validator_feedback", "retry_count"],
    "sql_validator": ["generated_sql"],
    "sql_refiner": ["generated_sql", "validator_feedback", "retry_count"],
    "executor": ["generated_sql", "hitl_approved"],
    "visualizer": ["row_count", "columns", "user_query"],
}

NODE_TRACKED_OUTPUT_KEYS = {
    "planner": ["is_ambiguous", "clarification_question", "intent_summary", "relevant_columns"],
    "sql_generator": ["generated_sql"],
    "sql_validator": ["is_valid_sql", "is_safe", "validator_feedback", "estimated_bytes", "safety_warning"],
    "sql_refiner": ["generated_sql", "retry_count"],
    "executor": ["row_count", "execution_time_ms", "execution_error", "status"],
    "visualizer": ["explanation", "chart_config", "status"],
}


def _snapshot_state(state: dict, keys: List[str]) -> dict:
    """Lấy snapshot của một số keys từ state (safe, không raise)."""
    snapshot = {}
    for k in keys:
        val = state.get(k)
        # Truncate large values
        if isinstance(val, (list, dict)) and len(str(val)) > 500:
            snapshot[k] = f"[{type(val).__name__} - {len(val)} items]"
        else:
            snapshot[k] = val
    return snapshot


def _diff_state(before: dict, after: dict, keys: List[str]) -> dict:
    """Tính diff giữa before và after state cho các keys."""
    changes = {}
    for k in keys:
        after_val = after.get(k)
        before_val = before.get(k)
        if after_val != before_val:
            if isinstance(after_val, (list, dict)) and len(str(after_val)) > 500:
                changes[k] = f"[{type(after_val).__name__} - {len(after_val)} items]"
            else:
                changes[k] = after_val
    return changes


# ─────────────────────────────────────────────
# @traced Decorator
# ─────────────────────────────────────────────

def traced(node_name: str):
    """
    Decorator tự động wrap agent node với tracing.
    
    Usage:
        @traced("planner")
        def planner_node(state: AgentState) -> AgentState:
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(state: dict) -> dict:
            start_ts = datetime.now(timezone.utc)
            start_time = time.perf_counter()

            input_keys = NODE_TRACKED_INPUT_KEYS.get(node_name, [])
            output_keys = NODE_TRACKED_OUTPUT_KEYS.get(node_name, [])

            node_trace = NodeTrace(
                node_name=node_name,
                start_time=start_ts.isoformat(),
                input_snapshot=_snapshot_state(state, input_keys),
                retry_count=state.get("retry_count", 0),
            )

            try:
                result = func(state)
                end_time = time.perf_counter()
                node_trace.end_time = datetime.now(timezone.utc).isoformat()
                node_trace.duration_ms = round((end_time - start_time) * 1000, 2)
                node_trace.output_changes = _diff_state(state, result, output_keys)
                node_trace.status = "success"

                # Attach trace to state
                traces = result.get("_node_traces", [])
                traces.append(asdict(node_trace))
                result["_node_traces"] = traces

                return result

            except Exception as e:
                end_time = time.perf_counter()
                node_trace.end_time = datetime.now(timezone.utc).isoformat()
                node_trace.duration_ms = round((end_time - start_time) * 1000, 2)
                node_trace.error = str(e)
                node_trace.status = "error"

                # Still attach trace even on error
                try:
                    traces = state.get("_node_traces", [])
                    traces.append(asdict(node_trace))
                    state["_node_traces"] = traces
                except Exception as trace_err:
                    logger.warning(f"[Tracing] Failed to attach error trace: {trace_err}")

                raise

        return wrapper
    return decorator


def record_llm_call(
    state: dict,
    node_name: str,
    prompt_text: str,
    response_text: str,
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
):
    """
    Ghi nhận LLM call vào trace gần nhất của node_name.
    Gọi từ trong node function sau khi có LLM response.
    """
    try:
        traces = state.get("_node_traces", [])
        # Find the most recent trace for this node
        for trace in reversed(traces):
            if trace.get("node_name") == node_name:
                trace["llm_model"] = model
                trace["llm_prompt_text"] = prompt_text[:2000]   # Truncate dài
                trace["llm_response_text"] = response_text[:2000]
                trace["llm_prompt_tokens"] = prompt_tokens
                trace["llm_completion_tokens"] = completion_tokens
                break
    except Exception as e:
        logger.warning(f"[Tracing] record_llm_call failed: {e}")


def build_agent_trace_from_state(state: dict) -> AgentTrace:
    """Build AgentTrace từ state sau khi agent chạy xong."""
    trace = AgentTrace(
        thread_id=state.get("thread_id", ""),
        user_query=state.get("user_query", ""),
        user_id=state.get("user_id", "anonymous"),
        final_status=state.get("status", ""),
        final_sql=state.get("generated_sql"),
        final_row_count=state.get("row_count", 0),
    )

    for node_dict in state.get("_node_traces", []):
        node = NodeTrace(**{
            k: v for k, v in node_dict.items()
            if k in NodeTrace.__dataclass_fields__
        })
        trace.add_node(node)

    return trace
