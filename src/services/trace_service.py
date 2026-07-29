"""
Trace Service — lưu và truy vấn Agent Traces từ database.
"""
import json
import logging
from typing import List, Optional

from src.agents.tracing import AgentTrace
from src.database import get_connection

logger = logging.getLogger(__name__)


def save_trace(trace: AgentTrace) -> bool:
    """Lưu AgentTrace vào database. Trả về True nếu thành công."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO agent_traces (
                trace_id, thread_id, user_query, user_id,
                nodes_json, total_duration_ms, total_llm_calls,
                total_prompt_tokens, total_completion_tokens,
                final_status, final_sql, score, score_breakdown_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            trace.trace_id,
            trace.thread_id,
            trace.user_query,
            trace.user_id,
            json.dumps(trace.nodes, ensure_ascii=False, default=str),
            trace.total_duration_ms,
            trace.total_llm_calls,
            trace.total_prompt_tokens,
            trace.total_completion_tokens,
            trace.final_status,
            trace.final_sql,
            trace.score,
            json.dumps(trace.score_breakdown) if trace.score_breakdown else None,
            trace.created_at,
        ))
        conn.commit()
        conn.close()
        logger.debug(f"[TraceService] Saved trace {trace.trace_id}")
        return True
    except Exception as e:
        logger.warning(f"[TraceService] Failed to save trace: {e}")
        return False


def get_traces(limit: int = 50, offset: int = 0) -> List[dict]:
    """Lấy danh sách traces gần nhất."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT trace_id, thread_id, user_query, user_id,
                   total_duration_ms, total_llm_calls,
                   total_prompt_tokens, total_completion_tokens,
                   final_status, final_sql, score, created_at
            FROM agent_traces
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?;
        """, (limit, offset))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"[TraceService] get_traces error: {e}")
        return []


def get_trace_detail(trace_id: str) -> Optional[dict]:
    """Lấy chi tiết một trace bao gồm nodes_json."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM agent_traces WHERE trace_id = ?;", (trace_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        result = dict(row)
        # Parse nodes JSON
        if result.get("nodes_json"):
            result["nodes"] = json.loads(result["nodes_json"])
        if result.get("score_breakdown_json"):
            result["score_breakdown"] = json.loads(result["score_breakdown_json"])
        return result
    except Exception as e:
        logger.error(f"[TraceService] get_trace_detail error: {e}")
        return None


def update_trace_score(trace_id: str, score: float, score_breakdown: dict) -> bool:
    """Cập nhật điểm số cho một trace (dùng sau khi benchmark)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE agent_traces
            SET score = ?, score_breakdown_json = ?
            WHERE trace_id = ?;
        """, (score, json.dumps(score_breakdown), trace_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"[TraceService] update_trace_score error: {e}")
        return False
