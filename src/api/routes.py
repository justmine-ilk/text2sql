from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from src.api.auth import create_token, require_role, verify_token
from src.agents.graph import execute_hitl_approval, run_agent_until_hitl, THREAD_STORE
from src.database import get_connection
from src.models.schemas import (
    ChatRequest, ChatResponse, HITLApproveRequest, LoginRequest,
    LoginResponse, QueryLogItem, SchemaItem, EvalSummary, TraceItem
)
from src.services.eval_service import run_benchmark_eval
from src.services.trace_service import get_traces, get_trace_detail

router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ? AND password_hash = ?", (req.username, req.password))
    user = cursor.fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Tên đăng nhập hoặc mật khẩu không chính xác.")

    token = create_token(user["username"], user["role"], user["email"])
    return LoginResponse(
        access_token=token,
        username=user["username"],
        role=user["role"],
        email=user["email"]
    )


@router.get("/auth/me")
async def get_me(user: dict = Depends(verify_token)):
    return user


@router.post("/chat/ask", response_model=ChatResponse)
async def ask_question(req: ChatRequest, user: dict = Depends(verify_token)):
    user_id = user.get("sub", "analyst")
    role = user.get("role", "analyst")

    state = run_agent_until_hitl(
        req.message,
        user_id=user_id,
        user_role=role,
        conversation_history=req.conversation_history
    )
    thread_id = state["thread_id"]

    return ChatResponse(
        thread_id=thread_id,
        status=state.get("status", "awaiting_approval"),
        user_query=state.get("user_query", req.message),
        generated_sql=state.get("generated_sql"),
        is_ambiguous=state.get("is_ambiguous", False),
        ambiguity_question=state.get("clarification_question"),
        estimated_bytes=state.get("estimated_bytes", 0),
        is_safe=state.get("is_safe", True),
        safety_warning=state.get("safety_warning"),
        cost_warning_level=state.get("cost_warning_level", "green"),
        results=state.get("execution_results"),
        columns=state.get("columns"),
        row_count=state.get("row_count", 0),
        chart_config=state.get("chart_config"),
        explanation=state.get("explanation"),
        error_message=state.get("validator_feedback")
    )


@router.post("/chat/approve", response_model=ChatResponse)
async def approve_sql(req: HITLApproveRequest, user: dict = Depends(verify_token)):
    thread_id = req.thread_id
    state = THREAD_STORE.get(thread_id)
    if not state:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên làm việc HITL hoặc đã hết hạn.")

    is_approved = (req.action == "approve")

    updated_state = execute_hitl_approval(state, approved=is_approved, modified_sql=req.modified_sql)
    THREAD_STORE.set(thread_id, updated_state)

    return ChatResponse(
        thread_id=thread_id,
        status=updated_state.get("status", "completed"),
        user_query=updated_state.get("user_query", ""),
        generated_sql=updated_state.get("generated_sql"),
        is_ambiguous=False,
        estimated_bytes=updated_state.get("estimated_bytes", 0),
        is_safe=updated_state.get("is_safe", True),
        cost_warning_level=updated_state.get("cost_warning_level", "green"),
        results=updated_state.get("execution_results"),
        columns=updated_state.get("columns"),
        row_count=updated_state.get("row_count", 0),
        chart_config=updated_state.get("chart_config"),
        explanation=updated_state.get("explanation"),
        error_message=updated_state.get("execution_error")
    )


@router.get("/admin/logs", response_model=List[QueryLogItem])
async def get_query_logs(
    user: dict = Depends(require_role("admin")),
    limit: int = Query(default=50, le=200)
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM query_logs ORDER BY id DESC LIMIT ?;", (limit,))
    rows = cursor.fetchall()
    conn.close()

    logs = []
    for r in rows:
        logs.append(QueryLogItem(
            id=r["id"],
            user_id=r["user_id"],
            user_role=r["user_role"],
            question=r["question"],
            generated_sql=r["generated_sql"],
            is_approved=bool(r["is_approved"]),
            execution_status=r["execution_status"] or "UNKNOWN",
            error_message=r["error_message"],
            row_count=r["row_count"] or 0,
            execution_time_ms=r["execution_time_ms"] or 0.0,
            estimated_bytes=r["estimated_bytes"] or 0,
            timestamp=r["timestamp"] or ""
        ))
    return logs


@router.get("/admin/schema", response_model=List[SchemaItem])
async def get_schema_metadata(user: dict = Depends(verify_token)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT column_name, data_type, description_vi, sample_values FROM schema_metadata;")
    rows = cursor.fetchall()
    conn.close()

    return [
        SchemaItem(
            column_name=r["column_name"],
            data_type=r["data_type"],
            description_vi=r["description_vi"],
            sample_values=r["sample_values"]
        ) for r in rows
    ]


@router.get("/traces", response_model=List[TraceItem])
async def list_agent_traces(
    user: dict = Depends(verify_token),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0)
):
    traces = get_traces(limit=limit, offset=offset)
    return [
        TraceItem(
            trace_id=t["trace_id"],
            thread_id=t.get("thread_id") or "",
            user_query=t["user_query"],
            user_id=t.get("user_id") or "anonymous",
            total_duration_ms=t.get("total_duration_ms") or 0.0,
            total_llm_calls=t.get("total_llm_calls") or 0,
            total_prompt_tokens=t.get("total_prompt_tokens") or 0,
            total_completion_tokens=t.get("total_completion_tokens") or 0,
            final_status=t.get("final_status") or "",
            final_sql=t.get("final_sql"),
            score=t.get("score"),
            created_at=str(t.get("created_at") or "")
        ) for t in traces
    ]


@router.get("/traces/{trace_id}")
async def get_trace_by_id(trace_id: str, user: dict = Depends(verify_token)):
    trace = get_trace_detail(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Không tìm thấy Agent Trace.")
    return trace


@router.post("/eval/run", response_model=EvalSummary)
async def run_eval(user: dict = Depends(require_role("admin"))):
    summary = run_benchmark_eval()
    return summary
