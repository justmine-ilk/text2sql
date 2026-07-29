import os
import sqlite3
import pandas as pd
from src.config import get_settings

settings = get_settings()


def get_db_path() -> str:
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        path = db_url.replace("sqlite:///", "")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        return os.path.abspath(path)
    return "online_retail.db"


def get_connection() -> sqlite3.Connection:
    path = get_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Table users (Analyst / Admin)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('analyst', 'admin')),
        email TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Table query_logs (Audit Trail)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS query_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        user_role TEXT NOT NULL,
        question TEXT NOT NULL,
        generated_sql TEXT,
        is_approved INTEGER DEFAULT 0,
        execution_status TEXT,
        error_message TEXT,
        row_count INTEGER DEFAULT 0,
        execution_time_ms REAL DEFAULT 0.0,
        estimated_bytes INTEGER DEFAULT 0,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. Table schema_metadata (Embedding & Descriptions)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS schema_metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        column_name TEXT UNIQUE NOT NULL,
        data_type TEXT NOT NULL,
        description_vi TEXT NOT NULL,
        sample_values TEXT
    );
    """)

    # 4. Table few_shot_examples (Q&A Examples for SQL Generation)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS few_shot_examples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_vi TEXT NOT NULL,
        sql_query TEXT NOT NULL,
        description TEXT,
        success_count INTEGER DEFAULT 0
    );
    """)

    # 5. Table agent_traces (Tracing & Observability)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS agent_traces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trace_id TEXT UNIQUE NOT NULL,
        thread_id TEXT,
        user_query TEXT NOT NULL,
        user_id TEXT,
        nodes_json TEXT NOT NULL,
        total_duration_ms REAL DEFAULT 0.0,
        total_llm_calls INTEGER DEFAULT 0,
        total_prompt_tokens INTEGER DEFAULT 0,
        total_completion_tokens INTEGER DEFAULT 0,
        final_status TEXT,
        final_sql TEXT,
        score REAL,
        score_breakdown_json TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()

    # Load CSV data into online_retail table if not exists or empty
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='online_retail';")
    table_exists = cursor.fetchone()

    csv_path = os.path.abspath(settings.csv_data_path)
    if not table_exists and os.path.exists(csv_path):
        print(f"[Database] Loading CSV data from {csv_path} into online_retail table...")
        df = pd.read_csv(csv_path)
        # Clean date format
        df["order_date"] = pd.to_datetime(df["order_date"]).dt.strftime("%Y-%m-%d")
        df.to_sql("online_retail", conn, if_exists="replace", index=False)
        print(f"[Database] Loaded {len(df)} rows into online_retail.")
    
    # Seed default users if empty
    cursor.execute("SELECT COUNT(*) as count FROM users")
    if cursor.fetchone()["count"] == 0:
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, email) VALUES (?, ?, ?, ?)",
            ("analyst", "analyst123", "analyst", "analyst@enterprise.com")
        )
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, email) VALUES (?, ?, ?, ?)",
            ("admin", "admin123", "admin", "admin@enterprise.com")
        )
        print("[Database] Seeded default users: analyst/analyst123, admin/admin123")

    # Seed schema metadata if empty
    cursor.execute("SELECT COUNT(*) as count FROM schema_metadata")
    if cursor.fetchone()["count"] == 0:
        schema_data = [
            ("customer_id", "INTEGER", "Mã định danh duy nhất của khách hàng", "13542, 23188"),
            ("order_date", "DATE", "Ngày đặt hàng (định dạng YYYY-MM-DD từ 2024-03-19 đến 2025-03-19)", "2024-12-17, 2025-01-31"),
            ("product_id", "INTEGER", "Mã sản phẩm", "784, 682, 204"),
            ("category_id", "INTEGER", "Mã danh mục sản phẩm (10, 20, 30, 40, 50)", "10, 20, 30, 40, 50"),
            ("category_name", "TEXT", "Tên danh mục sản phẩm (Electronics, Fashion, Home & Living, Books & Stationery, Sports & Outdoors)", "Electronics, Fashion"),
            ("product_name", "TEXT", "Tên sản phẩm cụ thể (Smartphone, Tablet, Laptop, Skirt, Pillow, Soccer Ball, v.v.)", "Smartphone, Laptop"),
            ("quantity", "INTEGER", "Số lượng sản phẩm mua trong đơn hàng", "1, 2, 3, 4, 5"),
            ("price", "REAL", "Đơn giá sản phẩm (USD/VND)", "373.36, 299.34"),
            ("payment_method", "TEXT", "Phương thức thanh toán (Credit Card, Bank Transfer, Cash on Delivery)", "Credit Card, Bank Transfer"),
            ("city", "TEXT", "Thành phố giao hàng", "New Oliviaberg, Aliciaberg"),
            ("review_score", "REAL", "Điểm đánh giá (1.0 đến 5.0)", "1.0, 3.0, 5.0"),
            ("gender", "TEXT", "Giới tính khách hàng ('M' hoặc 'F')", "M, F"),
            ("age", "INTEGER", "Tuổi khách hàng", "21, 34, 56, 64")
        ]
        cursor.executemany(
            "INSERT INTO schema_metadata (column_name, data_type, description_vi, sample_values) VALUES (?, ?, ?, ?)",
            schema_data
        )

    # Seed few-shot examples if empty
    cursor.execute("SELECT COUNT(*) as count FROM few_shot_examples")
    if cursor.fetchone()["count"] == 0:
        few_shots = [
            (
                "Tổng doanh thu theo từng danh mục sản phẩm",
                "SELECT category_name, ROUND(SUM(quantity * price), 2) AS total_revenue FROM online_retail GROUP BY category_name ORDER BY total_revenue DESC;",
                "Tính tổng tiền = quantity * price và gom nhóm theo category_name"
            ),
            (
                "Top 5 sản phẩm bán chạy nhất theo số lượng",
                "SELECT product_name, category_name, SUM(quantity) AS total_quantity FROM online_retail GROUP BY product_name, category_name ORDER BY total_quantity DESC LIMIT 5;",
                "Xếp hạng sản phẩm có tổng quantity lớn nhất"
            ),
            (
                "Doanh thu theo phương thức thanh toán trong tháng 12 năm 2024",
                "SELECT payment_method, ROUND(SUM(quantity * price), 2) AS total_revenue FROM online_retail WHERE order_date >= '2024-12-01' AND order_date <= '2024-12-31' GROUP BY payment_method ORDER BY total_revenue DESC;",
                "Lọc order_date trong tháng 12/2024 và nhóm theo payment_method"
            ),
            (
                "Số lượng đơn hàng và trung bình điểm đánh giá theo thành phố",
                "SELECT city, COUNT(*) AS total_orders, ROUND(AVG(review_score), 2) AS avg_review_score FROM online_retail WHERE review_score IS NOT NULL GROUP BY city ORDER BY total_orders DESC LIMIT 10;",
                "Đếm số đơn hàng và trung bình review_score theo city"
            ),
            (
                "Tỷ lệ khách hàng nam và nữ mua sắm danh mục Electronics",
                "SELECT gender, COUNT(DISTINCT customer_id) AS customer_count, SUM(quantity) AS total_items FROM online_retail WHERE category_name = 'Electronics' GROUP BY gender;",
                "Phân tích giới tính khách hàng mua đồ Electronics"
            )
        ]
        cursor.executemany(
            "INSERT INTO few_shot_examples (question_vi, sql_query, description) VALUES (?, ?, ?)",
            few_shots
        )

    conn.commit()
    conn.close()
    print("[Database] Initialization complete.")


if __name__ == "__main__":
    init_db()
