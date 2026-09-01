"""
Ingest CSV data from ./data into Postgres.

Uses:
  - python-dotenv to load DATABASE_URL / DATABASE_URL_POOLED from .env
  - psycopg (v3) with COPY FROM STDIN for fast bulk load

Usage:
  uv run python ingest.py
  uv run python ingest.py --drop        # drop + recreate tables
  uv run python ingest.py --truncate    # truncate before load (default)
  uv run python ingest.py --no-truncate # append (ON CONFLICT DO NOTHING not used; will error on PK collision)
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = pathlib.Path(__file__).parent / "data"

DDL = {
    "customers": """
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            customer_signup_date DATE,
            gender TEXT,
            age DOUBLE PRECISION,
            age_group TEXT,
            state TEXT,
            city TEXT,
            pincode_prefix INTEGER,
            customer_segment TEXT,
            preferred_device TEXT,
            preferred_payment_method TEXT,
            acquisition_channel TEXT,
            total_orders INTEGER,
            total_spend DOUBLE PRECISION,
            last_order_date DATE,
            average_order_value DOUBLE PRECISION,
            customer_status TEXT,
            loyalty_tier TEXT
        );
    """,
    "products": """
        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            product_name TEXT,
            category TEXT,
            subcategory TEXT,
            brand TEXT,
            price DOUBLE PRECISION,
            cost_price DOUBLE PRECISION,
            discount_range TEXT,
            rating_average DOUBLE PRECISION,
            rating_count INTEGER,
            stock_quantity INTEGER,
            product_launch_date DATE,
            product_type TEXT,
            return_rate_baseline DOUBLE PRECISION
        );
    """,
    "marketing_campaigns": """
        CREATE TABLE IF NOT EXISTS marketing_campaigns (
            campaign_id TEXT PRIMARY KEY,
            campaign_name TEXT,
            channel TEXT,
            campaign_start_date DATE,
            campaign_end_date DATE,
            campaign_type TEXT,
            target_segment TEXT,
            discount_percentage DOUBLE PRECISION,
            conversions INTEGER,
            revenue_generated DOUBLE PRECISION,
            impressions INTEGER,
            clicks INTEGER,
            campaign_cost DOUBLE PRECISION,
            roi DOUBLE PRECISION
        );
    """,
    "orders": """
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            customer_id TEXT REFERENCES customers(customer_id),
            order_date DATE,
            order_time TIME,
            order_status TEXT,
            shipping_method TEXT,
            delivery_city TEXT,
            delivery_state TEXT,
            coupon_code TEXT,
            discount_percentage DOUBLE PRECISION,
            marketing_channel TEXT,
            subtotal DOUBLE PRECISION,
            shipping_fee DOUBLE PRECISION,
            tax_amount DOUBLE PRECISION,
            final_amount DOUBLE PRECISION,
            campaign_id TEXT REFERENCES marketing_campaigns(campaign_id)
        );
    """,
    "order_items": """
        CREATE TABLE IF NOT EXISTS order_items (
            order_item_id TEXT PRIMARY KEY,
            order_id TEXT REFERENCES orders(order_id),
            product_id TEXT REFERENCES products(product_id),
            quantity INTEGER,
            unit_price DOUBLE PRECISION,
            discount_percentage DOUBLE PRECISION,
            item_revenue DOUBLE PRECISION,
            item_cost DOUBLE PRECISION,
            profit DOUBLE PRECISION
        );
    """,
    "payments": """
        CREATE TABLE IF NOT EXISTS payments (
            payment_id TEXT PRIMARY KEY,
            order_id TEXT REFERENCES orders(order_id),
            payment_date DATE,
            payment_method TEXT,
            payment_status TEXT,
            amount_paid DOUBLE PRECISION,
            transaction_fee DOUBLE PRECISION,
            refund_amount DOUBLE PRECISION
        );
    """,
    "shipments": """
        CREATE TABLE IF NOT EXISTS shipments (
            shipment_id TEXT PRIMARY KEY,
            order_id TEXT REFERENCES orders(order_id),
            warehouse_city TEXT,
            delivery_city TEXT,
            shipping_method TEXT,
            dispatch_date DATE,
            expected_delivery_date DATE,
            actual_delivery_date DATE,
            delivery_days DOUBLE PRECISION,
            delivery_status TEXT,
            delayed_flag INTEGER
        );
    """,
    "returns": """
        CREATE TABLE IF NOT EXISTS returns (
            return_id TEXT PRIMARY KEY,
            order_id TEXT REFERENCES orders(order_id),
            customer_id TEXT REFERENCES customers(customer_id),
            product_id TEXT REFERENCES products(product_id),
            return_date DATE,
            return_reason TEXT,
            refund_amount DOUBLE PRECISION,
            return_status TEXT
        );
    """,
    "customer_reviews": """
        CREATE TABLE IF NOT EXISTS customer_reviews (
            review_id TEXT PRIMARY KEY,
            order_id TEXT REFERENCES orders(order_id),
            customer_id TEXT REFERENCES customers(customer_id),
            product_id TEXT REFERENCES products(product_id),
            review_date DATE,
            rating INTEGER,
            review_sentiment TEXT,
            verified_purchase BOOLEAN
        );
    """,
}

CREATE_ORDER = [
    "marketing_campaigns",
    "customers",
    "products",
    "orders",
    "order_items",
    "payments",
    "shipments",
    "returns",
    "customer_reviews",
]

COPY_ORDER = CREATE_ORDER  # same order satisfies FK constraints

FILE_MAP = {
    "customers": "customers.csv",
    "products": "products.csv",
    "marketing_campaigns": "marketing_campaigns.csv",
    "orders": "orders.csv",
    "order_items": "order_items.csv",
    "payments": "payments.csv",
    "shipments": "shipments.csv",
    "returns": "returns.csv",
    "customer_reviews": "customer_reviews.csv",
}

COLUMNS = {
    "customers": "customer_id,customer_signup_date,gender,age,age_group,state,city,pincode_prefix,customer_segment,preferred_device,preferred_payment_method,acquisition_channel,total_orders,total_spend,last_order_date,average_order_value,customer_status,loyalty_tier",
    "products": "product_id,product_name,category,subcategory,brand,price,cost_price,discount_range,rating_average,rating_count,stock_quantity,product_launch_date,product_type,return_rate_baseline",
    "marketing_campaigns": "campaign_id,campaign_name,channel,campaign_start_date,campaign_end_date,campaign_type,target_segment,discount_percentage,conversions,revenue_generated,impressions,clicks,campaign_cost,roi",
    "orders": "order_id,customer_id,order_date,order_time,order_status,shipping_method,delivery_city,delivery_state,coupon_code,discount_percentage,marketing_channel,subtotal,shipping_fee,tax_amount,final_amount,campaign_id",
    "order_items": "order_item_id,order_id,product_id,quantity,unit_price,discount_percentage,item_revenue,item_cost,profit",
    "payments": "payment_id,order_id,payment_date,payment_method,payment_status,amount_paid,transaction_fee,refund_amount",
    "shipments": "shipment_id,order_id,warehouse_city,delivery_city,shipping_method,dispatch_date,expected_delivery_date,actual_delivery_date,delivery_days,delivery_status,delayed_flag",
    "returns": "return_id,order_id,customer_id,product_id,return_date,return_reason,refund_amount,return_status",
    "customer_reviews": "review_id,order_id,customer_id,product_id,review_date,rating,review_sentiment,verified_purchase",
}


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL_POOLED") or os.getenv("DATABASE_URL")
    if not url:
        print(
            "ERROR: Neither DATABASE_URL nor DATABASE_URL_POOLED is set.\n"
            "  1) Copy .env.example -> .env\n"
            "  2) Fill DATABASE_URL with your Postgres connection string, e.g.:\n"
            '     DATABASE_URL="postgresql://user:password@host:5432/dbname?sslmode=require"\n'
            "  3) Ensure python-dotenv is installed and .env is in project root.",
            file=sys.stderr,
        )
        sys.exit(1)
    url = url.strip().strip('"').strip("'").strip()
    if url.lower().startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url in ("xxxxxxxxxxx", "xxxxxx", ""):
        print(
            "ERROR: DATABASE_URL is still the placeholder from .env.example. "
            "Set a real Postgres URL in .env",
            file=sys.stderr,
        )
        sys.exit(1)
    return url


def get_connection(url: str):
    try:
        import psycopg  # psycopg v3
    except ImportError:
        print(
            'ERROR: psycopg is not installed. Run: uv add "psycopg[binary]"  or  pip install "psycopg[binary]"',
            file=sys.stderr,
        )
        sys.exit(1)
    return psycopg.connect(url)


def create_tables(conn, drop: bool = False) -> None:
    with conn.cursor() as cur:
        if drop:
            for tbl in reversed(CREATE_ORDER):
                cur.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")
                print(f"  dropped {tbl} (if existed)")
        for tbl in CREATE_ORDER:
            cur.execute(DDL[tbl])
            print(f"  ensured table {tbl}")
    conn.commit()


def truncate_tables(conn) -> None:
    tables_csv = ", ".join(CREATE_ORDER)
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {tables_csv} CASCADE;")
    conn.commit()
    print(f"  truncated {len(CREATE_ORDER)} tables (CASCADE)")


def copy_table(conn, table: str, csv_path: pathlib.Path) -> int:
    cols = COLUMNS[table]
    sql = f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT CSV, HEADER true, NULL '', DELIMITER ',')"
    with conn.cursor() as cur:
        if hasattr(cur, "copy"):
            with cur.copy(sql) as copy:
                with open(csv_path, "r", encoding="utf-8", newline="") as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        copy.write(chunk)
        else:
            # psycopg2 fallback
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                cur.copy_expert(sql, f)
        cur.execute(f"SELECT COUNT(*) FROM {table};")
        count = cur.fetchone()[0]
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest ./data CSVs into Postgres")
    parser.add_argument("--drop", action="store_true", help="DROP + recreate tables before load")
    parser.add_argument("--truncate", action="store_true", default=True, help="TRUNCATE before load (default: on)")
    parser.add_argument("--no-truncate", dest="truncate", action="store_false", help="Append without truncating")
    parser.add_argument("--data-dir", type=str, default=str(DATA_DIR), help="Path to CSV data dir")
    args = parser.parse_args()

    data_dir = pathlib.Path(args.data_dir)
    if not data_dir.exists():
        print(f"ERROR: data dir not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    for tbl, fname in FILE_MAP.items():
        p = data_dir / fname
        if not p.exists():
            print(f"ERROR: missing required CSV: {p}", file=sys.stderr)
            sys.exit(1)

    url = get_database_url()
    safe_url = url.split("@")[-1] if "@" in url else url[:40]
    print(f"Connecting to Postgres ({safe_url}) ...")

    with get_connection(url) as conn:
        conn.autocommit = False
        print("Ensuring tables ...")
        create_tables(conn, drop=args.drop)

        if args.truncate and not args.drop:
            print("Truncating tables ...")
            truncate_tables(conn)

        print("Copying CSVs ...")
        for tbl in COPY_ORDER:
            csv_path = data_dir / FILE_MAP[tbl]
            print(f"  COPY {tbl:22s} <- {csv_path.name} ...", end=" ", flush=True)
            try:
                n = copy_table(conn, tbl, csv_path)
                conn.commit()
                print(f"{n:,} rows")
            except Exception as e:
                conn.rollback()
                print(f"\nERROR copying {tbl}: {e}", file=sys.stderr)
                raise

        print("\nRow counts:")
        with conn.cursor() as cur:
            for tbl in COPY_ORDER:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                n = cur.fetchone()[0]
                print(f"  {tbl:22s} {n:,}")

        print("\nDone.")


if __name__ == "__main__":
    main()
