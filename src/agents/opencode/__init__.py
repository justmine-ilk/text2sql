"""
OpenCode Agent Engine Package.
Ported directly from OpenCode (anomalyco/opencode dev branch).
"""

from src.agents.opencode.compactor import SessionContextCompactor
from src.agents.opencode.harness import PermissionHarness, ExecutionMode
from src.agents.opencode.subagents import SubagentOrchestrator
from src.agents.opencode.event_bus import agent_event_bus, AgentEvent
from src.agents.opencode.loop import OpenCodeAgentLoop

__all__ = [
    "SessionContextCompactor",
    "PermissionHarness",
    "ExecutionMode",
    "SubagentOrchestrator",
    "agent_event_bus",
    "AgentEvent",
    "OpenCodeAgentLoop",
]
