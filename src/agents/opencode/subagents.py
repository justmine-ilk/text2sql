"""
OpenCode Subagent Orchestrator & Specialist Runners.
Ported from packages/opencode/src/agent/subagent.ts

Mỗi Subagent đóng vai trò chuyên biệt với isolated context window & tool permissions:
- PlannerSubagent (Plan mode)
- SQLGeneratorSubagent (Plan mode)
- SQLValidatorSubagent (Plan mode)
- SQLRefinerSubagent (Plan mode)
- VisualizerSubagent (Plan mode)
"""
import logging
from typing import Dict, Any, List, Optional

from src.agents.opencode.harness import PermissionHarness, ExecutionMode
from src.agents.opencode.event_bus import agent_event_bus
from src.agents.state import AgentState

logger = logging.getLogger(__name__)


class BaseSubagent:
    name: str
    mode: ExecutionMode

    def __init__(self, name: str, mode: ExecutionMode = ExecutionMode.PLAN):
        self.name = name
        self.mode = mode
        self.harness = PermissionHarness(mode=mode)

    def execute(self, state: AgentState) -> AgentState:
        agent_event_bus.emit("step_start", self.name, {"user_query": state.get("user_query")})
        try:
            result = self.run_logic(state)
            agent_event_bus.emit("step_complete", self.name, {"status": result.get("status")})
            return result
        except Exception as err:
            agent_event_bus.emit("step_error", self.name, {"error": str(err)})
            raise

    def run_logic(self, state: AgentState) -> AgentState:
        raise NotImplementedError


class SubagentOrchestrator:
    """Điều phối và quản lý danh sách Subagents chuyên biệt."""
    def __init__(self):
        self.subagents: Dict[str, BaseSubagent] = {}

    def register(self, subagent: BaseSubagent):
        self.subagents[subagent.name] = subagent
        logger.info(f"[Subagent Orchestrator] Registered specialist subagent '{subagent.name}' ({subagent.mode.value.upper()})")

    def run_subagent(self, name: str, state: AgentState) -> AgentState:
        if name not in self.subagents:
            raise KeyError(f"Subagent '{name}' chưa được đăng ký trong orchestrator.")
        return self.subagents[name].execute(state)
