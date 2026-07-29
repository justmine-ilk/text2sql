"""
OpenCode Session Context Compactor Manager.
Ported from packages/opencode/src/session/compaction.ts

Tự động nén và quản lý Token Budget cho conversation history:
1. Đếm token ước tính (characters / 4).
2. Khi vượt quá 80% Context Window Budget (default 8,000 tokens), tự động kích hoạt Summarizer.
3. Tóm tắt các turn hội thoại cũ thành 1 System Summary Block.
4. Bảo tồn System Prompt gốc + Dynamic Schema + 2 Turn hội thoại gần nhất.
"""
import logging
from typing import List, Dict, Any, Tuple

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_WINDOW_TOKENS = 8000
COMPACTION_THRESHOLD_RATIO = 0.8  # 80% budget


def estimate_tokens(text: str) -> int:
    """Ước tính số token cơ bản (khoảng 4 ký tự / token cho mixed EN/VI)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: List[BaseMessage]) -> int:
    """Đếm tổng số tokens của danh sách BaseMessage."""
    total = 0
    for msg in messages:
        total += estimate_tokens(str(msg.content))
    return total


class SessionContextCompactor:
    def __init__(self, context_budget: int = DEFAULT_CONTEXT_WINDOW_TOKENS):
        self.context_budget = context_budget
        self.threshold_tokens = int(context_budget * COMPACTION_THRESHOLD_RATIO)

    def should_compact(self, messages: List[BaseMessage]) -> bool:
        """Kiểm tra xem có cần kích hoạt compaction không."""
        total_tokens = estimate_messages_tokens(messages)
        return total_tokens >= self.threshold_tokens

    def compact(self, messages: List[BaseMessage], llm: Any = None) -> Tuple[List[BaseMessage], bool]:
        """
        Thực hiện compactor theo mẫu của OpenCode:
        - Giữ lại System Prompt đầu tiên (index 0).
        - Lấy 2 turns gần nhất ở cuối.
        - Tóm tắt đoạn giữa thành 1 System Summary Message.
        """
        if len(messages) <= 3 or not self.should_compact(messages):
            return messages, False

        system_prompt = messages[0] if isinstance(messages[0], SystemMessage) else None
        start_idx = 1 if system_prompt else 0

        # Lấy 2 messages gần nhất ở cuối (User query & AI response)
        recent_messages = messages[-2:]
        middle_messages = messages[start_idx:-2]

        if not middle_messages:
            return messages, False

        # Build summary text cho middle messages
        summary_lines = []
        for msg in middle_messages:
            role = "User" if isinstance(msg, HumanMessage) else ("Assistant" if isinstance(msg, AIMessage) else "System")
            content_snippet = str(msg.content)[:200]
            summary_lines.append(f"[{role}]: {content_snippet}")

        summary_text = (
            "📌 [OpenCode Context Summary Block]:\n"
            "Các trao đổi cũ trước đó đã được nén để tiết kiệm Token Budget:\n" +
            "\n".join(summary_lines)
        )

        compacted_messages: List[BaseMessage] = []
        if system_prompt:
            compacted_messages.append(system_prompt)

        compacted_messages.append(SystemMessage(content=summary_text))
        compacted_messages.extend(recent_messages)

        tokens_before = estimate_messages_tokens(messages)
        tokens_after = estimate_messages_tokens(compacted_messages)

        logger.info(
            f"[OpenCode Compactor] Compacted conversation: {len(messages)} -> {len(compacted_messages)} messages | "
            f"Tokens: {tokens_before} -> {tokens_after} (Saved {tokens_before - tokens_after} tokens)"
        )

        return compacted_messages, True
