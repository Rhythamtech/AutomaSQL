from __future__ import annotations
import re
from src.utils.database import DatabaseUtils
from langchain.agents import create_agent
from langchain.tools import tool
from src.agents.base import agent_factory_model
from config.constant import GET_DB_COLUMN_SCHEMA, GET_DB_TABLE_SCHEMA
from config.constant import SQL_ENGINEER_SYSTEM_PROMPT


_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|VACUUM|CALL)\b",
    re.IGNORECASE,
)
_READ_ONLY = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE | re.DOTALL)
MAX_ROWS = 20
def guardrail_DDL_DML(query: str):
    if _FORBIDDEN.search(query):
        return {"error": "Query contains a forbidden write/DDL keyword."}
    if not _READ_ONLY.match(query):
        return {"error": "Only SELECT / WITH ... SELECT statements are allowed."}
    # Allow a single trailing semicolon, but reject stacked statements.
    stripped = query.strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1]
    if ";" in stripped:
        return {"error": "Run one statement at a time; remove extra semicolons."}
    return None

def extract_sql_blocks(text):
    pattern = r"```sql\s*(.*?)\s*```"
    matches = re.findall(pattern, text, flags=re.DOTALL)
    if not matches:
        return None
    return matches[0]


def build_schema_context():
    context = ""
    conn = None
    db_utils = DatabaseUtils()
    try:
        conn = db_utils.get_connection()
        tables = db_utils.execute_query(conn=conn, query=GET_DB_TABLE_SCHEMA)
    except Exception as e:
        raise RuntimeError(f"Could not load schema context: {type(e).__name__}: {e}") from e

    try:
        for table in tables:
            context += f"> Table- {table['table_name']}\n"
            columns = db_utils.execute_query(
                conn=conn, query=GET_DB_COLUMN_SCHEMA, params=(table["table_name"],)
            )
            for col in columns:
                context += f"    {col['column_name']} | {col['data_type']} \n"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return context


def build_sql_engineer_agent(verbose: bool = False):
    """Build the LangChain SQL engineer agent graph."""
    context_schema = build_schema_context()
    prompt = SQL_ENGINEER_SYSTEM_PROMPT + f"\nDatabase Schema Context : {context_schema}" + f"\nMax Row Count : {MAX_ROWS}"

    model = agent_factory_model(level="high")
    return create_agent(
        model=model,
        system_prompt=prompt,
        tools=[],
        debug=verbose,
        name="sql_engineer",
    )
    

def engineer(message: str, verbose: bool = False) -> dict:
    agent = build_sql_engineer_agent(verbose=verbose)
    result = agent.invoke({"messages": [{"role": "user", "content": message}]})

    messages = result.get("messages", [])
    if not messages:
        return {"error": "The SQL engineer returned no response.", "status": "FAILED"}

    output = messages[-1].content
    query = extract_sql_blocks(text=output)
    if not query:
        return {"error": "The SQL engineer returned no SQL query.", "status": "FAILED"}

    guardrail_response = guardrail_DDL_DML(query)
    if guardrail_response is not None:
        return {
            "error": guardrail_response["error"],
            "status": "DDL_DML_FOUND",
        }

    return {"sql": query, "status": "SUCCESS"}
    