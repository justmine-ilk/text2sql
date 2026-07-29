"""
Pydantic Output Schemas cho LangChain with_structured_output().
Thay thế toàn bộ việc parse text thủ công bằng split("```json").

Mỗi schema là typed, validated, và crash-safe.
"""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Planner Node Output
# ─────────────────────────────────────────────

class PlannerOutput(BaseModel):
    """Structured output từ Planner Agent."""
    is_ambiguous: bool = Field(
        description="True nếu câu hỏi mơ hồ hoặc thiếu thông tin để tạo SQL"
    )
    clarification_question: Optional[str] = Field(
        default=None,
        description="Câu hỏi làm rõ gửi lại cho người dùng (khi is_ambiguous=True)"
    )
    intent_summary: str = Field(
        description="Tóm tắt ý định phân tích: Aggregation / Trend / Comparison / Ranking / General"
    )
    relevant_columns: List[str] = Field(
        default_factory=list,
        description="Danh sách tên cột có thể liên quan đến câu hỏi"
    )
    complexity: Literal["simple", "medium", "complex"] = Field(
        default="medium",
        description="Độ phức tạp ước tính của câu truy vấn"
    )


# ─────────────────────────────────────────────
# Visualizer / Explainer Node Output
# ─────────────────────────────────────────────

class ChartConfig(BaseModel):
    """Cấu hình biểu đồ để frontend render."""
    type: Literal["bar", "line", "pie", "table"] = Field(
        description="Loại biểu đồ phù hợp nhất"
    )
    title: str = Field(description="Tiêu đề biểu đồ")
    xAxisKey: str = Field(description="Tên cột dùng cho trục X / nhãn")
    seriesKeys: List[str] = Field(description="Danh sách tên cột dùng cho giá trị / series")


class VisualizerOutput(BaseModel):
    """Structured output từ Visualizer Agent."""
    explanation: str = Field(
        description="Giải thích 2-4 câu tiếng Việt, nêu bật insight quan trọng nhất"
    )
    chart_config: ChartConfig = Field(
        description="Cấu hình biểu đồ phù hợp với dữ liệu"
    )


# ─────────────────────────────────────────────
# LLM Judge Output (dùng cho benchmark scoring)
# ─────────────────────────────────────────────

class JudgeScore(BaseModel):
    """Điểm số từ LLM Judge đánh giá logic equivalence."""
    score: float = Field(
        ge=0.0, le=100.0,
        description="Điểm logic equivalence từ 0 đến 100"
    )
    reasoning: str = Field(
        description="Giải thích ngắn gọn tại sao cho điểm này"
    )
    is_equivalent: bool = Field(
        description="True nếu SQL agent về cơ bản trả lời đúng câu hỏi"
    )


# ─────────────────────────────────────────────
# Tool Schemas (Input/Output cho Tool Registry)
# ─────────────────────────────────────────────

class SchemaColumnInfo(BaseModel):
    column_name: str
    data_type: str
    description_vi: str
    sample_values: Optional[str] = None


class FewShotExample(BaseModel):
    question_vi: str
    sql_query: str
    description: Optional[str] = None
    relevance_score: float = 1.0  # keyword match score


class ValidationResult(BaseModel):
    is_valid: bool
    is_safe: bool
    error_message: Optional[str] = None
    safety_warning: Optional[str] = None
    estimated_bytes: int = 0
    warning_level: Literal["green", "yellow", "red"] = "green"


class CostEstimate(BaseModel):
    estimated_bytes: int
    estimated_rows: int
    is_over_limit: bool
    warning_level: Literal["green", "yellow", "red"]
    warning_message: Optional[str] = None
