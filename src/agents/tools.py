"""
Agent Tool Registry — lấy cảm hứng từ OpenCode tool system.

Mỗi tool là một hàm Python có:
- Typed input/output (Pydantic)
- Clear description cho LLM hiểu khi nào dùng
- Permission model (read_only vs read_write)
- Error handling riêng biệt

LLM sẽ dùng Function Calling để gọi các tools này
thay vì ta hardcode toàn bộ flow.
"""
import re
import sqlite3
import time
from typing import List, Optional

from langchain_core.tools import tool

from src.agents.errors import SQLValidationError
from src.agents.output_schemas import (
    CostEstimate,
    FewShotExample,
    SchemaColumnInfo,
    ValidationResult,
)
from src.database import get_connection

# ─── Constants ───────────────────────────────
AVG_ROW_SIZE_BYTES = 90  # Ước tính trung bình mỗi row ~90 bytes
MAX_BYTES_LIMIT = 100_000_000  # 100MB

FORBIDDEN_KEYWORDS = [
    r"\bDROP\b", r"\bDELETE\b", r"\bUPDATE\b", r"\bINSERT\b",
    r"\bALTER\b", r"\bCREATE\b", r"\bTRUNCATE\b", r"\bEXEC\b",
    r"\bGRANT\b", r"\bREPLACE\b", r"\bATTACH\b",
]

VALID_COLUMNS = {
    "customer_id", "order_date", "product_id", "category_id",
    "category_name", "product_name", "quantity", "price",
    "payment_method", "city", "review_score", "gender", "age"
}

VALID_TABLES = {"online_retail"}


# ─────────────────────────────────────────────
# TOOL 1: Query Schema
# ─────────────────────────────────────────────

@tool
def query_schema(table_name: str = "online_retail") -> List[dict]:
    """
    Tra cứu metadata của bảng và cột trong database.
    Trả về danh sách cột với kiểu dữ liệu, mô tả tiếng Việt và giá trị mẫu.
    Dùng khi cần biết cấu trúc database để sinh SQL chính xác.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT column_name, data_type, description_vi, sample_values "
            "FROM schema_metadata ORDER BY id;"
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "column_name": r["column_name"],
                "data_type": r["data_type"],
                "description_vi": r["description_vi"],
                "sample_values": r["sample_values"],
            }
            for r in rows
        ]
    except Exception as e:
        return [{"error": f"Không thể lấy schema: {str(e)}"}]


def get_schema_columns() -> List[SchemaColumnInfo]:
    """Internal helper để lấy schema cho prompt building (không phải LangChain tool)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT column_name, data_type, description_vi, sample_values FROM schema_metadata;"
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            SchemaColumnInfo(
                column_name=r["column_name"],
                data_type=r["data_type"],
                description_vi=r["description_vi"],
                sample_values=r["sample_values"],
            )
            for r in rows
        ]
    except Exception:
        return []


# ─────────────────────────────────────────────
# TOOL 2: Search Few-Shot Examples
# ─────────────────────────────────────────────

@tool
def search_few_shots(question: str, top_k: int = 3) -> List[dict]:
    """
    Tìm ví dụ SQL mẫu (few-shot examples) liên quan đến câu hỏi.
    Dùng keyword matching để chọn những ví dụ phù hợp nhất.
    Trả về top_k ví dụ có độ liên quan cao nhất.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT question_vi, sql_query, description FROM few_shot_examples ORDER BY success_count DESC;"
        )
        all_examples = cursor.fetchall()
        conn.close()

        # Keyword matching scoring
        question_lower = question.lower()
        question_words = set(re.findall(r"\w+", question_lower))

        scored = []
        for ex in all_examples:
            ex_words = set(re.findall(r"\w+", ex["question_vi"].lower()))
            overlap = len(question_words & ex_words)
            if overlap > 0:
                scored.append((overlap, ex))

        # Sort by relevance descending
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [ex for _, ex in scored[:top_k]]

        # Fallback: nếu không có overlap, trả về top theo success_count
        if not top:
            cursor2 = get_connection().cursor()
            cursor2.execute(
                f"SELECT question_vi, sql_query, description FROM few_shot_examples "
                f"ORDER BY success_count DESC LIMIT {top_k};"
            )
            top = cursor2.fetchall()

        return [
            {
                "question_vi": ex["question_vi"],
                "sql_query": ex["sql_query"],
                "description": ex["description"],
            }
            for ex in top
        ]
    except Exception as e:
        return [{"error": f"Không thể tìm few-shot examples: {str(e)}"}]


def get_relevant_few_shots(question: str, top_k: int = 3) -> List[FewShotExample]:
    """Internal helper để lấy few-shot examples (không phải LangChain tool)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT question_vi, sql_query, description FROM few_shot_examples ORDER BY success_count DESC;"
        )
        all_examples = cursor.fetchall()
        conn.close()

        question_lower = question.lower()
        question_words = set(re.findall(r"\w+", question_lower))

        scored = []
        for ex in all_examples:
            ex_words = set(re.findall(r"\w+", ex["question_vi"].lower()))
            overlap = len(question_words & ex_words)
            scored.append((overlap, ex))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [ex for _, ex in scored[:top_k]]
        if not top and all_examples:
            top = list(all_examples[:top_k])

        return [
            FewShotExample(
                question_vi=ex["question_vi"],
                sql_query=ex["sql_query"],
                description=ex["description"],
                relevance_score=float(sc) if sc > 0 else 0.5,
            )
            for sc, ex in scored[:top_k]
        ]
    except Exception:
        return []


# ─────────────────────────────────────────────
# TOOL 3: Validate SQL
# ─────────────────────────────────────────────

@tool
def validate_sql(sql: str) -> dict:
    """
    Kiểm tra tính hợp lệ và an toàn của câu SQL trước khi thực thi.
    Kiểm tra: forbidden keywords, SELECT-only, syntax qua EXPLAIN QUERY PLAN.
    Trả về is_valid, is_safe, error_message và estimated_bytes.
    """
    result = _validate_sql_internal(sql)
    return result.model_dump()


def _validate_sql_internal(sql: str) -> ValidationResult:
    """Internal validation logic trả về Pydantic model."""
    sql = sql.strip()

    if not sql:
        return ValidationResult(
            is_valid=False,
            is_safe=False,
            error_message="Câu lệnh SQL rỗng.",
            warning_level="red",
        )

    # 1. Forbidden keywords check
    for pattern in FORBIDDEN_KEYWORDS:
        if re.search(pattern, sql, re.IGNORECASE):
            return ValidationResult(
                is_valid=False,
                is_safe=False,
                safety_warning=f"Phát hiện từ khóa bị cấm: {pattern}",
                error_message=f"CHỈ cho phép SELECT. Từ khóa bị cấm: {pattern}",
                warning_level="red",
            )

    # 2. Must start with SELECT or WITH
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.IGNORECASE):
        return ValidationResult(
            is_valid=False,
            is_safe=False,
            error_message="Câu lệnh phải bắt đầu bằng SELECT hoặc WITH.",
            warning_level="red",
        )

    # 3. Auto-append LIMIT if missing
    if "LIMIT" not in sql.upper():
        sql = sql.rstrip(";") + " LIMIT 1000;"

    # 4. Syntax check via EXPLAIN QUERY PLAN
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"EXPLAIN QUERY PLAN {sql}")
        plan_rows = cursor.fetchall()
        conn.close()

        # Estimate cost from plan
        cost = _estimate_cost_from_plan(plan_rows)

        warning_level = "green"
        if cost.estimated_bytes > 50_000_000:
            warning_level = "red"
        elif cost.estimated_bytes > 10_000_000:
            warning_level = "yellow"

        return ValidationResult(
            is_valid=True,
            is_safe=True,
            estimated_bytes=cost.estimated_bytes,
            warning_level=warning_level,
        )

    except sqlite3.Error as err:
        return ValidationResult(
            is_valid=False,
            is_safe=True,
            error_message=f"Lỗi cú pháp SQLite: {str(err)}",
            warning_level="red",
        )


# ─────────────────────────────────────────────
# TOOL 4: Estimate Cost
# ─────────────────────────────────────────────

@tool
def estimate_cost(sql: str) -> dict:
    """
    Ước tính chi phí quét dữ liệu của câu SQL bằng EXPLAIN QUERY PLAN.
    Trả về estimated_bytes, warning_level ('green'/'yellow'/'red') và is_over_limit.
    Dùng trước khi thực thi để cảnh báo người dùng.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"EXPLAIN QUERY PLAN {sql}")
        plan_rows = cursor.fetchall()
        conn.close()
        cost = _estimate_cost_from_plan(plan_rows)
        return cost.model_dump()
    except Exception as e:
        return CostEstimate(
            estimated_bytes=0,
            estimated_rows=0,
            is_over_limit=False,
            warning_level="green",
            warning_message=f"Không thể ước tính cost: {str(e)}",
        ).model_dump()


def _estimate_cost_from_plan(plan_rows) -> CostEstimate:
    """Parse EXPLAIN QUERY PLAN output để ước tính rows scanned."""
    # SQLite EXPLAIN QUERY PLAN trả về: (id, parent, notused, detail)
    # Phân tích detail string để đoán scan type
    total_estimated_rows = 0

    for row in plan_rows:
        detail = ""
        if hasattr(row, "__getitem__"):
            try:
                detail = str(row[3]) if len(row) > 3 else str(row[-1])
            except (IndexError, TypeError):
                detail = str(row)

        detail_lower = detail.lower()

        if "scan" in detail_lower and "index" not in detail_lower:
            # Full table scan — ước tính 50,000 rows
            total_estimated_rows += 50_000
        elif "scan" in detail_lower and "index" in detail_lower:
            # Index scan — ước tính 5,000 rows
            total_estimated_rows += 5_000
        elif "search" in detail_lower:
            # Index search (point lookup) — ước tính 100 rows
            total_estimated_rows += 100
        else:
            total_estimated_rows += 1_000  # default

    if total_estimated_rows == 0:
        total_estimated_rows = 1_000

    estimated_bytes = total_estimated_rows * AVG_ROW_SIZE_BYTES
    is_over = estimated_bytes > MAX_BYTES_LIMIT

    warning_level = "green"
    if estimated_bytes > 50_000_000:
        warning_level = "red"
    elif estimated_bytes > 10_000_000:
        warning_level = "yellow"

    return CostEstimate(
        estimated_bytes=estimated_bytes,
        estimated_rows=total_estimated_rows,
        is_over_limit=is_over,
        warning_level=warning_level,
        warning_message=(
            f"⚠️ Ước tính quét {estimated_bytes:,} bytes ({total_estimated_rows:,} dòng). "
            "Vượt ngưỡng!" if is_over else None
        ),
    )


# ─────────────────────────────────────────────
# TOOL 5: Execute Query (Internal use only)
# ─────────────────────────────────────────────

def execute_query_internal(sql: str, limit: int = 1000) -> dict:
    """
    Thực thi SQL đã được validate và HITL approve.
    Không expose như LangChain tool vì cần HITL approval trước.
    """
    start = time.time()
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchmany(limit)  # Dùng fetchmany thay vì fetchall
        columns = [d[0] for d in cursor.description] if cursor.description else []
        results = [dict(zip(columns, row)) for row in rows]
        duration_ms = round((time.time() - start) * 1000, 2)
        conn.close()
        return {
            "success": True,
            "results": results,
            "columns": columns,
            "row_count": len(results),
            "execution_time_ms": duration_ms,
        }
    except sqlite3.Error as err:
        duration_ms = round((time.time() - start) * 1000, 2)
        raise SQLValidationError(str(err), sql=sql)


# ─────────────────────────────────────────────
# All available tools list (for LLM binding)
# ─────────────────────────────────────────────

ALL_TOOLS = [query_schema, search_few_shots, validate_sql, estimate_cost]
READ_ONLY_TOOLS = [query_schema, search_few_shots, estimate_cost]
