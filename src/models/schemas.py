from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    email: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    user_id: Optional[str] = "analyst"
    role: Optional[str] = "analyst"
    conversation_history: Optional[List[Dict[str, str]]] = Field(default_factory=list)


class HITLApproveRequest(BaseModel):
    thread_id: str
    action: str = Field(..., description="approve or reject")
    modified_sql: Optional[str] = None
    user_id: Optional[str] = "analyst"


class ChatResponse(BaseModel):
    thread_id: str
    status: str  # 'need_clarification', 'awaiting_approval', 'completed', 'error'
    user_query: str
    generated_sql: Optional[str] = None
    is_ambiguous: bool = False
    ambiguity_question: Optional[str] = None
    estimated_bytes: int = 0
    is_safe: bool = True
    safety_warning: Optional[str] = None
    cost_warning_level: Optional[str] = "green"
    results: Optional[List[Dict[str, Any]]] = None
    columns: Optional[List[str]] = None
    row_count: int = 0
    chart_config: Optional[Dict[str, Any]] = None
    explanation: Optional[str] = None
    error_message: Optional[str] = None


class QueryLogItem(BaseModel):
    id: int
    user_id: str
    user_role: str
    question: str
    generated_sql: Optional[str]
    is_approved: bool
    execution_status: str
    error_message: Optional[str]
    row_count: int
    execution_time_ms: float
    estimated_bytes: int
    timestamp: str


class SchemaItem(BaseModel):
    column_name: str
    data_type: str
    description_vi: str
    sample_values: Optional[str] = None


class EvalResultItem(BaseModel):
    question: str
    gold_sql: str
    generated_sql: str
    is_execution_matched: bool
    composite_score: float = 0.0
    score_breakdown: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class EvalSummary(BaseModel):
    total_test_cases: int
    passed_cases: int
    execution_accuracy: float
    average_score: float = 0.0
    details: List[EvalResultItem]


class TraceItem(BaseModel):
    trace_id: str
    thread_id: str
    user_query: str
    user_id: str
    total_duration_ms: float
    total_llm_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    final_status: str
    final_sql: Optional[str] = None
    score: Optional[float] = None
    created_at: str
