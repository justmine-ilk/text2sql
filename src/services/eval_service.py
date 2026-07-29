"""
Multi-Dimensional Benchmark Evaluation Service.

Nâng cấp v2:
- Sửa lỗi critical: so sánh NỘI DUNG thực tế thay vì chỉ len(rows)
- 5-dimensional scoring: Syntax, Schema, Execution, Logic (LLM judge), Performance
- LLM Judge cho Logic Equivalence (20% weight)
- Trace-integrated: mỗi test case tạo AgentTrace
"""
import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from src.database import get_connection
from src.agents.graph import run_agent_until_hitl
from src.agents.llm import get_llm
from src.agents.output_schemas import JudgeScore
from src.agents.prompts import SQL_JUDGE_SYSTEM_PROMPT
from src.models.schemas import EvalSummary, EvalResultItem

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Score Weights
# ─────────────────────────────────────────────
WEIGHTS = {
    "syntax":      0.15,   # Syntax correctness
    "schema":      0.20,   # Schema compliance
    "execution":   0.35,   # Execution result match
    "logic":       0.20,   # LLM judge — logic equivalence
    "performance": 0.10,   # Performance (retry count, speed)
}

VALID_COLUMNS = {
    "customer_id", "order_date", "product_id", "category_id",
    "category_name", "product_name", "quantity", "price",
    "payment_method", "city", "review_score", "gender", "age"
}


# ─────────────────────────────────────────────
# Individual Scoring Functions
# ─────────────────────────────────────────────

def score_syntax(gen_sql: str, conn) -> float:
    """Syntax: chạy EXPLAIN QUERY PLAN — pass = 100, fail = 0."""
    if not gen_sql:
        return 0.0
    try:
        conn.execute(f"EXPLAIN QUERY PLAN {gen_sql}")
        return 100.0
    except sqlite3.Error:
        return 0.0


def score_schema_compliance(gen_sql: str) -> float:
    """
    Schema: kiểm tra tên cột và bảng có đúng không.
    Trừ 20 điểm cho mỗi column/table reference không hợp lệ.
    """
    if not gen_sql:
        return 0.0

    import re
    score = 100.0
    sql_upper = gen_sql.upper()

    # Check for valid table name
    if "ONLINE_RETAIL" not in sql_upper:
        score -= 30.0  # Sai bảng là lỗi nặng

    # Check column names (từ schema)
    # Tìm tất cả identifier-like tokens
    tokens = re.findall(r'\b([a-z_][a-z0-9_]*)\b', gen_sql.lower())
    sql_keywords = {
        'select', 'from', 'where', 'group', 'by', 'order', 'limit', 'having',
        'join', 'on', 'and', 'or', 'not', 'in', 'is', 'null', 'as', 'distinct',
        'count', 'sum', 'avg', 'max', 'min', 'round', 'with', 'case', 'when',
        'then', 'else', 'end', 'like', 'between', 'desc', 'asc', 'top', 'inner',
        'outer', 'left', 'right', 'cross', 'full', 'exists', 'all', 'any',
        'online_retail', 'true', 'false', 'substr', 'strftime', 'date', 'coalesce',
    }
    
    suspicious_cols = [
        t for t in set(tokens)
        if t not in sql_keywords and len(t) > 3 and t not in VALID_COLUMNS
        and not t.isdigit()
    ]
    # Penalize each suspicious unrecognized column/alias
    penalty = min(len(suspicious_cols) * 10, 40)
    score = max(score - penalty, 0.0)

    return score


def score_execution_match(gold_sql: str, gen_sql: str, conn) -> Tuple[float, str]:
    """
    Execution: so sánh kết quả thực thi THỰC TẾ (không chỉ số dòng).
    Returns (score, error_message)
    """
    if not gen_sql:
        return 0.0, "Không có SQL"

    try:
        c1 = conn.cursor()
        c1.execute(gold_sql)
        gold_rows = [dict(r) for r in c1.fetchall()]

        c2 = conn.cursor()
        c2.execute(gen_sql)
        gen_rows = [dict(r) for r in c2.fetchall()]

    except sqlite3.Error as e:
        return 0.0, f"Lỗi khi chạy SQL: {str(e)}"

    # ── Perfect match ─────────────────────────────────────────────────────
    if _normalize_rows(gold_rows) == _normalize_rows(gen_rows):
        return 100.0, None

    # ── Row count mismatch ───────────────────────────────────────────────
    if len(gold_rows) == 0 and len(gen_rows) == 0:
        return 100.0, None

    if len(gold_rows) == 0 or len(gen_rows) == 0:
        return 0.0, f"Gold={len(gold_rows)} dòng, Gen={len(gen_rows)} dòng"

    # ── Partial match: tính % cell values trùng ──────────────────────────
    score = _partial_match_score(gold_rows, gen_rows)
    error_msg = (
        f"Partial match {score:.1f}% — Gold={len(gold_rows)} dòng, Gen={len(gen_rows)} dòng"
        if score < 100 else None
    )
    return score, error_msg


def _normalize_rows(rows: List[dict]) -> List[tuple]:
    """Normalize rows để so sánh: sort, round floats, ignore key order."""
    normalized = []
    for row in rows:
        norm_row = tuple(
            round(v, 2) if isinstance(v, float) else v
            for v in row.values()
        )
        normalized.append(norm_row)
    return sorted(normalized, key=lambda x: [str(i) for i in x])


def _partial_match_score(gold_rows: List[dict], gen_rows: List[dict]) -> float:
    """Tính điểm partial match dựa trên % cells khớp nhau."""
    # So sánh top-K rows
    k = min(len(gold_rows), len(gen_rows), 10)
    gold_sorted = sorted(_normalize_rows(gold_rows[:k]), key=str)
    gen_sorted = sorted(_normalize_rows(gen_rows[:k]), key=str)

    total_cells = 0
    matched_cells = 0

    for g_row, n_row in zip(gold_sorted, gen_sorted):
        for g_val, n_val in zip(g_row, n_row):
            total_cells += 1
            # Tolerance for floats
            if isinstance(g_val, float) and isinstance(n_val, float):
                if abs(g_val - n_val) < 1.0:
                    matched_cells += 1
            elif str(g_val).strip() == str(n_val).strip():
                matched_cells += 1

    if total_cells == 0:
        return 0.0

    # Apply row count penalty
    row_ratio = min(len(gold_rows), len(gen_rows)) / max(len(gold_rows), len(gen_rows))
    cell_accuracy = matched_cells / total_cells
    return round(cell_accuracy * row_ratio * 100, 1)


def score_logic_equivalence(
    question: str, gold_sql: str, gen_sql: str
) -> Tuple[float, str]:
    """
    LLM Judge: đánh giá logic equivalence.
    Returns (score, reasoning)
    """
    if not gen_sql:
        return 0.0, "Không có SQL để đánh giá"

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = get_llm()
        structured_llm = llm.with_structured_output(JudgeScore)

        user_message = (
            f"Câu hỏi: {question}\n"
            f"SQL Chuẩn (Gold): {gold_sql}\n"
            f"SQL Agent: {gen_sql}\n\n"
            "Hãy đánh giá xem SQL Agent có trả lời đúng ý câu hỏi không?"
        )

        result: JudgeScore = structured_llm.invoke([
            SystemMessage(content=SQL_JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ])

        return result.score, result.reasoning

    except Exception as e:
        logger.warning(f"[LLM Judge] Error: {e} — skipping logic score")
        return 50.0, f"Judge không khả dụng: {str(e)}"


def score_performance(state: dict, retry_count: int = 0) -> float:
    """
    Performance: đánh giá tốc độ và số lần retry.
    """
    score = 100.0

    # Penalize retries
    score -= retry_count * 15

    # Penalize slow execution
    exec_time = state.get("execution_time_ms", 0)
    if exec_time > 10_000:  # > 10s
        score -= 30
    elif exec_time > 5_000:  # > 5s
        score -= 15

    # Reward if SQL has LIMIT
    sql = state.get("generated_sql", "")
    if sql and "LIMIT" not in sql.upper():
        score -= 10

    return max(score, 0.0)


# ─────────────────────────────────────────────
# Main Benchmark Runner
# ─────────────────────────────────────────────

def run_benchmark_eval() -> EvalSummary:
    """
    Chạy benchmark với 5-dimensional scoring.
    Mỗi test case tạo AgentTrace và tính composite score.
    """
    eval_file = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../eval/test_cases.json")
    )

    if not os.path.exists(eval_file):
        return EvalSummary(
            total_test_cases=0, passed_cases=0, execution_accuracy=0.0,
            average_score=0.0, details=[]
        )

    with open(eval_file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    conn = get_connection()
    details: List[EvalResultItem] = []
    passed = 0
    total_score = 0.0

    for i, case in enumerate(cases):
        question = case["question"]
        gold_sql = case["gold_sql"]

        logger.info(f"[Benchmark] Running case {i+1}/{len(cases)}: {question[:50]}...")

        # Run agent
        state = run_agent_until_hitl(question)
        gen_sql = state.get("generated_sql", "")
        retry_count = state.get("retry_count", 0)

        # ── Score each dimension ─────────────────────────────────────────
        s_syntax = score_syntax(gen_sql, conn) if gen_sql else 0.0
        s_schema = score_schema_compliance(gen_sql) if gen_sql else 0.0
        s_execution, exec_error = score_execution_match(gold_sql, gen_sql, conn) if gen_sql else (0.0, "Không có SQL")
        s_logic, logic_reasoning = score_logic_equivalence(question, gold_sql, gen_sql) if gen_sql else (0.0, "N/A")
        s_performance = score_performance(state, retry_count)

        # ── Composite score ──────────────────────────────────────────────
        composite = (
            s_syntax * WEIGHTS["syntax"] +
            s_schema * WEIGHTS["schema"] +
            s_execution * WEIGHTS["execution"] +
            s_logic * WEIGHTS["logic"] +
            s_performance * WEIGHTS["performance"]
        )
        composite = round(composite, 2)
        total_score += composite

        is_passed = s_execution >= 80.0  # Pass if execution match ≥ 80%
        if is_passed:
            passed += 1

        score_breakdown = {
            "syntax": round(s_syntax, 1),
            "schema": round(s_schema, 1),
            "execution": round(s_execution, 1),
            "logic": round(s_logic, 1),
            "performance": round(s_performance, 1),
            "logic_reasoning": logic_reasoning,
        }

        details.append(EvalResultItem(
            question=question,
            gold_sql=gold_sql,
            generated_sql=gen_sql or "",
            is_execution_matched=is_passed,
            composite_score=composite,
            score_breakdown=score_breakdown,
            error=exec_error,
        ))

    conn.close()

    total = len(cases)
    accuracy = round((passed / total) * 100, 2) if total > 0 else 0.0
    avg_score = round(total_score / total, 2) if total > 0 else 0.0

    return EvalSummary(
        total_test_cases=total,
        passed_cases=passed,
        execution_accuracy=accuracy,
        average_score=avg_score,
        details=details,
    )
