"""
Error taxonomy cho Text-to-SQL Agent.
Thay vì catch generic Exception, mỗi loại lỗi có type riêng,
giúp debug, logging và xử lý phân biệt rõ ràng.
"""


class AgentError(Exception):
    """Base class cho tất cả lỗi trong agent system."""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


class LLMError(AgentError):
    """Lỗi khi gọi LLM API (timeout, rate limit, invalid key, v.v.)."""
    pass


class LLMParseError(AgentError):
    """Lỗi khi parse output từ LLM (JSON sai format, missing field, v.v.)."""
    def __init__(self, message: str, raw_output: str = "", details: dict = None):
        super().__init__(message, details)
        self.raw_output = raw_output


class SQLGenerationError(AgentError):
    """Lỗi khi agent không sinh được SQL từ câu hỏi."""
    pass


class SQLValidationError(AgentError):
    """Lỗi khi SQL không qua validation (syntax error, forbidden keywords, v.v.)."""
    def __init__(self, message: str, sql: str = "", details: dict = None):
        super().__init__(message, details)
        self.sql = sql


class SQLExecutionError(AgentError):
    """Lỗi khi thực thi SQL trên database."""
    def __init__(self, message: str, sql: str = "", details: dict = None):
        super().__init__(message, details)
        self.sql = sql


class CostLimitError(AgentError):
    """Lỗi khi ước tính cost vượt ngưỡng giới hạn."""
    def __init__(self, message: str, estimated_bytes: int = 0, limit_bytes: int = 0):
        super().__init__(message, {"estimated_bytes": estimated_bytes, "limit_bytes": limit_bytes})
        self.estimated_bytes = estimated_bytes
        self.limit_bytes = limit_bytes


class HITLError(AgentError):
    """Lỗi liên quan đến HITL workflow (thread không tồn tại, đã hết hạn, v.v.)."""
    pass


class AuthenticationError(AgentError):
    """Lỗi xác thực người dùng."""
    pass


class TracingError(AgentError):
    """Lỗi không nghiêm trọng khi ghi trace — không được làm crash agent."""
    pass
