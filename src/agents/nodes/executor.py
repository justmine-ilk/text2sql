"""
Executor Node — thực thi SQL đã được HITL approve.

Nâng cấp v2:
- fetchmany() thay vì fetchall() để tránh OOM với large datasets
- Explicit timeout (sqlite3 timeout parameter)
- Better audit logging với execution context
- @traced decorator
"""
import logging
import time

import sqlite3

from src.agents.state import AgentState
from src.database import get_connection
from src.agents.tracing import traced

logger = logging.getLogger(__name__)

QUERY_TIMEOUT_SECONDS = 30
MAX_ROWS_RETURN = 1000


@traced("executor")
def executor_node(state: AgentState) -> AgentState:
    """
    Executor: chạy SQL đã được approve, ghi audit log.
    
    Input state: generated_sql, hitl_approved, user_id, user_role
    Output state: execution_results, columns, row_count, execution_time_ms, status
    """
    sql = state.get("generated_sql", "")
    user_id = state.get("user_id", "analyst")
    user_role = state.get("user_role", "analyst")
    user_query = state.get("user_query", "")

    if not sql:
        state["status"] = "failed"
        state["execution_error"] = "SQL rỗng — không thể thực thi."
        return state

    if not state.get("hitl_approved", False):
        state["status"] = "failed"
        state["execution_error"] = "SQL chưa được phê duyệt (HITL required)."
        return state

    start_time = time.perf_counter()
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Set timeout
        conn.execute(f"PRAGMA busy_timeout = {QUERY_TIMEOUT_SECONDS * 1000}")

        cursor.execute(sql)
        rows = cursor.fetchmany(MAX_ROWS_RETURN)   # Dùng fetchmany tránh OOM
        columns = [d[0] for d in cursor.description] if cursor.description else []
        results = [dict(zip(columns, row)) for row in rows]

        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        state["execution_results"] = results
        state["columns"] = columns
        state["row_count"] = len(results)
        state["execution_error"] = None
        state["execution_time_ms"] = execution_time_ms
        state["status"] = "executed"

        # ── Audit log ────────────────────────────────────────────────────────
        try:
            cursor.execute("""
                INSERT INTO query_logs (
                    user_id, user_role, question, generated_sql, is_approved,
                    execution_status, row_count, execution_time_ms, estimated_bytes
                ) VALUES (?, ?, ?, ?, 1, 'SUCCESS', ?, ?, ?);
            """, (
                user_id, user_role, user_query, sql,
                len(results), execution_time_ms,
                state.get("estimated_bytes", 0)
            ))
            conn.commit()
        except Exception as log_err:
            logger.warning(f"[Executor] Audit log failed (non-critical): {log_err}")

        conn.close()
        logger.info(
            f"[Executor] SUCCESS — {len(results)} rows in {execution_time_ms}ms"
        )

    except sqlite3.Error as err:
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.error(f"[Executor] SQL execution error: {err}")
        state["status"] = "failed"
        state["execution_error"] = f"Lỗi khi thực thi SQL: {str(err)}"
        state["execution_results"] = None
        state["columns"] = None
        state["row_count"] = 0
        state["execution_time_ms"] = execution_time_ms

        # Log failure
        try:
            conn2 = get_connection()
            c2 = conn2.cursor()
            c2.execute("""
                INSERT INTO query_logs (
                    user_id, user_role, question, generated_sql, is_approved,
                    execution_status, error_message, execution_time_ms
                ) VALUES (?, ?, ?, ?, 1, 'FAILED', ?, ?);
            """, (user_id, user_role, user_query, sql, str(err), execution_time_ms))
            conn2.commit()
            conn2.close()
        except Exception:
            pass

    return state
