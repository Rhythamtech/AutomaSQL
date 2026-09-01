from dotenv import load_dotenv
from psycopg.connection import Connection
import psycopg  # psycopg v3
import sys
import os

from psycopg.rows import DictRow, dict_row

load_dotenv()



class DatabaseUtils :
    
    def __init__(self):
        self.URL = self._get_database_url()
    
    def _get_database_url(self) -> str:
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
        return url

    def get_connection(self):
        return psycopg.connect(self.URL, row_factory=dict_row)
    
    
    def execute_query(self,conn : Connection[DictRow], query :str, params : tuple ):
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchall()
        except Exception as e:
            print(f"An error occurred: {e}")
            return []


if __name__ == "__main__":
    from config.constant  import GET_DB_COLUMN_SCHEMA, GET_DB_TABLE_SCHEMA
    
    db = DatabaseUtils()
    conn = db.get_connection()
    
    
    tables = db.execute_query(conn,GET_DB_TABLE_SCHEMA,{})
    for table in tables :
        columns = db.execute_query(conn=conn,query= GET_DB_COLUMN_SCHEMA,params=(table.get('table_name'),))
        print(table)
        print(columns)