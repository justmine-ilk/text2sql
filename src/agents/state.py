from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict):
    # ── Identity ──────────────────────────────
    thread_id: str
    user_query: str
    user_id: str
    user_role: str

    # ── Conversation Memory ───────────────────
    conversation_history: List[Dict[str, str]]  # [{"role": "user/assistant", "content": "..."}]

    # ── Planner output ────────────────────────
    is_ambiguous: bool
    clarification_question: Optional[str]
    intent_summary: Optional[str]
    relevant_columns: List[str]
    query_complexity: Optional[str]  # "simple", "medium", "complex"

    # ── SQL Generator & Validator output ──────
    generated_sql: Optional[str]
    is_valid_sql: bool
    validator_feedback: Optional[str]
    retry_count: int

    # ── Cost Guard ────────────────────────────
    estimated_bytes: int
    estimated_rows: int
    is_safe: bool
    safety_warning: Optional[str]
    cost_warning_level: Optional[str]  # "green", "yellow", "red"

    # ── HITL output ───────────────────────────
    hitl_approved: bool
    hitl_action: Optional[str]  # 'approved', 'rejected', 'modified'

    # ── Executor output ───────────────────────
    execution_results: Optional[List[Dict[str, Any]]]
    columns: Optional[List[str]]
    row_count: int
    execution_error: Optional[str]
    execution_time_ms: float

    # ── Visualizer output ─────────────────────
    explanation: Optional[str]
    chart_config: Optional[Dict[str, Any]]

    # ── Tracing (internal) ───────────────────
    _node_traces: List[Dict[str, Any]]  # List of NodeTrace dicts

    # ── Final status ──────────────────────────
    status: str  # 'need_clarification', 'awaiting_approval', 'executed', 'completed', 'failed', 'rejected'
