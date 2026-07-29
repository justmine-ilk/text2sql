"""
OpenCode Agent Event Bus & Telemetry System.
Ported from packages/opencode/src/bus/index.ts

Hệ thống Event Bus phát sinh event theo thời gian thực:
- agent:step_start
- agent:llm_call
- agent:tool_call
- agent:perm_check
- agent:compaction
- agent:step_complete
"""
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    event_type: str                   # 'step_start', 'tool_call', 'perm_check', 'compaction', 'step_complete'
    node_name: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "node_name": self.node_name,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class AgentEventBus:
    def __init__(self):
        self._listeners: List[Callable[[AgentEvent], None]] = []

    def subscribe(self, listener: Callable[[AgentEvent], None]):
        """Đăng ký listener nhận event."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[AgentEvent], None]):
        """Hủy đăng ký listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event_type: str, node_name: str, data: Dict[str, Any] = None):
        """Phát biểu sự kiện đến tất cả subscribers."""
        event = AgentEvent(event_type=event_type, node_name=node_name, data=data or {})
        logger.debug(f"[AgentEventBus] Emit [{event.event_type}] for node '{event.node_name}'")

        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception as err:
                logger.warning(f"[AgentEventBus] Listener error: {err}")


# Global Event Bus instance
agent_event_bus = AgentEventBus()
