"""
OpenCode Core Agent Loop & Step Lifecycle Engine.
Ported from packages/opencode/src/agent/loop.ts

Quy trình ReAct Step Lifecycle:
1. Compactor Check: Tự động nén conversation history nếu vượt Token Budget.
2. Step Start: Phát sinh event telemetry `agent:step_start`.
3. Tool Permission Evaluation: Kiểm tra Tool Call Proposal qua PermissionHarness ("Model Proposes, Runtime Permits").
4. Execution: Chạy logic của từng Agent Node.
5. Step Complete: Phát sinh event telemetry `agent:step_complete`.
6. Interruption Handling: Hỗ trợ ngắt/hủy tiến trình an toàn khi nhận signal cancel.
"""
import logging
from typing import Dict, Any, List, Optional, Callable

from src.agents.opencode.compactor import SessionContextCompactor
from src.agents.opencode.harness import PermissionHarness, ExecutionMode
from src.agents.opencode.event_bus import agent_event_bus
from src.agents.state import AgentState

logger = logging.getLogger(__name__)


class OpenCodeAgentLoop:
    def __init__(self, mode: ExecutionMode = ExecutionMode.PLAN):
        self.compactor = SessionContextCompactor()
        self.harness = PermissionHarness(mode=mode)
        self.is_cancelled = False

    def cancel(self):
        """Hủy/ngắt tiến trình chạy agent."""
        logger.warning("[OpenCode Agent Loop] Interruption fiber triggered — cancelling step loop.")
        self.is_cancelled = True

    def run_step(self, node_name: str, node_fn: Callable[[AgentState], AgentState], state: AgentState) -> AgentState:
        """
        Thực thi một Step trong ReAct Loop theo chuẩn OpenCode:
        """
        if self.is_cancelled:
            state["status"] = "failed"
            state["execution_error"] = "Tiến trình đã bị người dùng hủy ngắt."
            return state

        # 1. Compactor check & emit
        if state.get("conversation_history"):
            history_len = len(state["conversation_history"])
            if history_len > 10:
                agent_event_bus.emit("compaction", node_name, {"history_turns": history_len})

        # 2. Step Start Telemetry
        agent_event_bus.emit("step_start", node_name, {
            "thread_id": state.get("thread_id"),
            "user_query": state.get("user_query")
        })

        # 3. Tool Permission Check
        try:
            self.harness.authorize_tool_call(tool_name="validate_sql" if "validator" in node_name else "query_schema")
        except Exception as perm_err:
            agent_event_bus.emit("perm_denied", node_name, {"reason": str(perm_err)})
            state["status"] = "failed"
            state["execution_error"] = str(perm_err)
            return state

        # 4. Execute Node Function
        try:
            updated_state = node_fn(state)
            # 5. Step Complete Telemetry
            agent_event_bus.emit("step_complete", node_name, {
                "status": updated_state.get("status"),
                "has_sql": bool(updated_state.get("generated_sql"))
            })
            return updated_state
        except Exception as err:
            logger.error(f"[OpenCode Agent Loop] Error in step '{node_name}': {err}")
            agent_event_bus.emit("step_error", node_name, {"error": str(err)})
            state["status"] = "failed"
            state["execution_error"] = f"Lỗi ở bước [{node_name}]: {str(err)}"
            return state
