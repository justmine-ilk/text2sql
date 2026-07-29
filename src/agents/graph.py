"""
Agent Graph — OpenCode Agent Engine v3 Workflow Orchestration.

Nâng cấp v3 (Ported from OpenCode dev branch):
- OpenCodeAgentLoop: ReAct Step Lifecycle Management
- PermissionHarness: Model Proposes, Runtime Permits (Plan Mode vs Build Mode)
- SessionContextCompactor: Auto Token Budget Compaction & History Summarization
- AgentEventBus: Real-time Telemetry Events
"""
import asyncio
import logging
import time
import uuid
from typing import Optional

from langgraph.graph import END, StateGraph

from src.agents.nodes.executor import executor_node
from src.agents.nodes.planner import planner_node
from src.agents.nodes.sql_generator import sql_generator_node
from src.agents.nodes.sql_refiner import sql_refiner_node
from src.agents.nodes.sql_validator import sql_validator_node
from src.agents.nodes.visualizer import visualizer_node
from src.agents.state import AgentState
from src.agents.tracing import build_agent_trace_from_state

# Import OpenCode Engine v3 Modules
from src.agents.opencode.loop import OpenCodeAgentLoop
from src.agents.opencode.harness import ExecutionMode, PermissionHarness
from src.agents.opencode.compactor import SessionContextCompactor
from src.agents.opencode.event_bus import agent_event_bus

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# OpenCode Wrapped Agent Nodes
# ─────────────────────────────────────────────

opencode_loop_plan = OpenCodeAgentLoop(mode=ExecutionMode.PLAN)
opencode_loop_build = OpenCodeAgentLoop(mode=ExecutionMode.BUILD)


def opencode_planner_node(state: AgentState) -> AgentState:
    return opencode_loop_plan.run_step("planner", planner_node, state)


def opencode_generator_node(state: AgentState) -> AgentState:
    return opencode_loop_plan.run_step("sql_generator", sql_generator_node, state)


def opencode_validator_node(state: AgentState) -> AgentState:
    return opencode_loop_plan.run_step("sql_validator", sql_validator_node, state)


def opencode_refiner_node(state: AgentState) -> AgentState:
    return opencode_loop_plan.run_step("sql_refiner", sql_refiner_node, state)


# ─────────────────────────────────────────────
# Router Functions
# ─────────────────────────────────────────────

def route_planner(state: AgentState) -> str:
    """Sau planner: nếu mơ hồ → END (chờ user), nếu rõ → generate SQL."""
    if state.get("is_ambiguous", False):
        return END
    if state.get("status") == "failed":
        return END
    return "sql_generator"


def route_validator(state: AgentState) -> str:
    """Sau validator: nếu valid → END (chờ HITL), nếu invalid → refine."""
    if state.get("status") == "failed":
        return END
    if not state.get("is_valid_sql", False):
        return "sql_refiner"
    # Valid SQL → pause để chờ HITL approval
    return END


def route_refiner(state: AgentState) -> str:
    """Sau refiner: nếu quá max retry → END failed, nếu không → validate lại."""
    if state.get("status") == "failed":
        return END
    return "sql_validator"


# ─────────────────────────────────────────────
# Graph Builder
# ─────────────────────────────────────────────

def create_agent_graph():
    """Build and compile the LangGraph agent workflow wrapped with OpenCode Engine."""
    workflow = StateGraph(AgentState)

    # Add OpenCode Engine Nodes
    workflow.add_node("planner", opencode_planner_node)
    workflow.add_node("sql_generator", opencode_generator_node)
    workflow.add_node("sql_validator", opencode_validator_node)
    workflow.add_node("sql_refiner", opencode_refiner_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("visualizer", visualizer_node)

    # Set Entry Point
    workflow.set_entry_point("planner")

    # Add Edges
    workflow.add_conditional_edges("planner", route_planner, {
        "sql_generator": "sql_generator",
        END: END,
    })
    workflow.add_edge("sql_generator", "sql_validator")
    workflow.add_conditional_edges("sql_validator", route_validator, {
        "sql_refiner": "sql_refiner",
        END: END,
    })
    workflow.add_conditional_edges("sql_refiner", route_refiner, {
        "sql_validator": "sql_validator",
        END: END,
    })
    workflow.add_edge("executor", "visualizer")
    workflow.add_edge("visualizer", END)

    return workflow.compile()


# Global agent instance
agent = create_agent_graph()


# ─────────────────────────────────────────────
# HITL Thread Store (In-memory với TTL)
# ─────────────────────────────────────────────

class HITLThreadStore:
    """Thread-safe in-memory HITL state store với TTL cleanup."""

    def __init__(self, ttl_seconds: int = 1800):  # 30 phút
        self._store: dict = {}
        self._ttl = ttl_seconds

    def set(self, thread_id: str, state: AgentState):
        self._store[thread_id] = {
            "state": state,
            "created_at": time.time(),
        }

    def get(self, thread_id: str) -> Optional[AgentState]:
        entry = self._store.get(thread_id)
        if not entry:
            return None
        # Check TTL
        if time.time() - entry["created_at"] > self._ttl:
            del self._store[thread_id]
            return None
        return entry["state"]

    def delete(self, thread_id: str):
        self._store.pop(thread_id, None)

    def cleanup_expired(self):
        """Xóa các threads đã hết TTL."""
        now = time.time()
        expired = [
            k for k, v in self._store.items()
            if now - v["created_at"] > self._ttl
        ]
        for k in expired:
            del self._store[k]
        if expired:
            logger.info(f"[HITL Store] Cleaned up {len(expired)} expired threads.")
        return len(expired)

    def __contains__(self, thread_id: str):
        return self.get(thread_id) is not None


# Global thread store
THREAD_STORE = HITLThreadStore(ttl_seconds=1800)


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def run_agent_until_hitl(
    user_query: str,
    user_id: str = "analyst",
    user_role: str = "analyst",
    conversation_history: list = None,
) -> AgentState:
    """
    Chạy OpenCode Agent Engine v3 từ user_query → dừng tại HITL.
    """
    thread_id = str(uuid.uuid4())
    initial_state: AgentState = {
        "thread_id": thread_id,
        "user_query": user_query,
        "user_id": user_id,
        "user_role": user_role,
        "conversation_history": conversation_history or [],
        "is_ambiguous": False,
        "clarification_question": None,
        "intent_summary": None,
        "relevant_columns": [],
        "query_complexity": None,
        "generated_sql": None,
        "is_valid_sql": False,
        "validator_feedback": None,
        "retry_count": 0,
        "estimated_bytes": 0,
        "estimated_rows": 0,
        "is_safe": True,
        "safety_warning": None,
        "cost_warning_level": "green",
        "hitl_approved": False,
        "hitl_action": None,
        "execution_results": None,
        "columns": None,
        "row_count": 0,
        "execution_error": None,
        "execution_time_ms": 0.0,
        "explanation": None,
        "chart_config": None,
        "_node_traces": [],
        "status": "awaiting_approval",
    }

    try:
        final_state = agent.invoke(initial_state)
    except Exception as e:
        logger.error(f"[Graph] OpenCode Agent invocation error: {e}")
        initial_state["status"] = "failed"
        initial_state["execution_error"] = f"Lỗi hệ thống agent: {str(e)}"
        return initial_state

    # Determine status
    if final_state.get("is_ambiguous"):
        final_state["status"] = "need_clarification"
    elif final_state.get("status") == "failed":
        pass  # Keep failed status
    elif final_state.get("is_valid_sql"):
        final_state["status"] = "awaiting_approval"
    else:
        final_state["status"] = "failed"

    # Store in thread store for HITL
    THREAD_STORE.set(thread_id, final_state)

    # Save trace to DB
    _save_trace_async(final_state)

    return final_state


def execute_hitl_approval(
    state: AgentState,
    approved: bool,
    modified_sql: Optional[str] = None,
) -> AgentState:
    """
    Xử lý HITL decision (approve/reject) trong Build Mode.
    """
    state["hitl_approved"] = approved
    state["hitl_action"] = "approved" if approved else "rejected"

    if modified_sql:
        state["generated_sql"] = modified_sql
        from src.agents.tools import _validate_sql_internal
        result = _validate_sql_internal(modified_sql)
        if not result.is_valid:
            state["status"] = "failed"
            state["execution_error"] = f"SQL đã sửa không hợp lệ: {result.error_message}"
            return state

    if not approved:
        state["status"] = "rejected"
        state["explanation"] = "Người dùng đã từ chối thực thi truy vấn SQL này."
        return state

    # Run Executor & Visualizer in BUILD Mode under OpenCode Agent Loop
    try:
        state = opencode_loop_build.run_step("executor", executor_node, state)
        if state.get("status") == "executed":
            state = opencode_loop_build.run_step("visualizer", visualizer_node, state)
    except Exception as e:
        logger.error(f"[Graph] OpenCode BUILD Mode HITL execution error: {e}")
        state["status"] = "failed"
        state["execution_error"] = str(e)

    # Save final trace
    _save_trace_async(state)

    return state


def _save_trace_async(state: AgentState):
    """Lưu agent trace vào DB."""
    try:
        from src.services.trace_service import save_trace
        agent_trace = build_agent_trace_from_state(state)
        save_trace(agent_trace)
    except Exception as e:
        logger.warning(f"[Graph] Trace save failed (non-critical): {e}")
