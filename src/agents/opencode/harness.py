"""
OpenCode Tool Permission Harness Engine.
Ported from packages/opencode/src/permission/harness.ts

Nguyên tắc cốt lõi: "Model Proposes, Runtime Permits"
- LLM chỉ đóng vai trò đề xuất Tool Proposal (JSON tool_call).
- Permission Harness độc lập kiểm tra quyền theo ExecutionMode trước khi cho phép Runtime thực thi.
"""
import enum
import logging
from typing import Dict, Any, List, Optional

from src.agents.errors import AgentError

logger = logging.getLogger(__name__)


class ExecutionMode(str, enum.Enum):
    PLAN = "plan"    # Read-only exploration mode (Planner, Validator)
    BUILD = "build"  # Full execution mode (Executor - sau khi HITL Approved)


class PermissionViolationError(AgentError):
    def __init__(self, tool_name: str, mode: ExecutionMode, reason: str):
        message = f"[OpenCode Permission Harness Violation] Tool '{tool_name}' bị từ chối ở chế độ {mode.value.upper()}: {reason}"
        super().__init__(message, {"tool_name": tool_name, "mode": mode.value, "reason": reason})


# Bảng phân quyền Tool Permissions
TOOL_PERMISSIONS: Dict[str, List[ExecutionMode]] = {
    "query_schema": [ExecutionMode.PLAN, ExecutionMode.BUILD],
    "search_few_shots": [ExecutionMode.PLAN, ExecutionMode.BUILD],
    "validate_sql": [ExecutionMode.PLAN, ExecutionMode.BUILD],
    "estimate_cost": [ExecutionMode.PLAN, ExecutionMode.BUILD],
    "execute_query_internal": [ExecutionMode.BUILD],  # CHỈ cho phép ở BUILD mode khi HITL approved
}


class PermissionHarness:
    def __init__(self, mode: ExecutionMode = ExecutionMode.PLAN):
        self.mode = mode

    def set_mode(self, mode: ExecutionMode):
        logger.info(f"[Permission Harness] Switched Execution Mode -> {mode.value.upper()}")
        self.mode = mode

    def authorize_tool_call(self, tool_name: str, tool_args: Dict[str, Any] = None) -> bool:
        """
        Kiểm tra xem Tool Proposal của LLM có được phép chạy ở chế độ hiện tại không.
        If unauthorized, raises PermissionViolationError.
        """
        allowed_modes = TOOL_PERMISSIONS.get(tool_name, [ExecutionMode.BUILD])

        if self.mode not in allowed_modes:
            raise PermissionViolationError(
                tool_name=tool_name,
                mode=self.mode,
                reason=f"Tool này yêu cầu quyền {', '.join([m.value.upper() for m in allowed_modes])} nhưng hệ thống đang ở chế độ {self.mode.value.upper()}."
            )

        # Kiểm tra nội dung câu SQL đối với tool validate hoặc execute
        if tool_args and "sql" in tool_args:
            sql_upper = str(tool_args["sql"]).upper()
            forbidden = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE"]
            for word in forbidden:
                if f" {word} " in f" {sql_upper} " or sql_upper.startswith(f"{word} "):
                    raise PermissionViolationError(
                        tool_name=tool_name,
                        mode=self.mode,
                        reason=f"Phát hiện từ khóa nguy hiểm '{word}' trong câu SQL proposal."
                    )

        logger.info(f"[Permission Harness] Authorized tool '{tool_name}' in mode {self.mode.value.upper()}")
        return True
