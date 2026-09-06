import logging
import ast
from pathlib import Path
import pandas as pd
from langchain.agents import create_agent
from src.agents.base import agent_factory_model

logger = logging.getLogger(__name__)


PANDAS_ENGINEER_SYSTEM_PROMPT = """
You are a Pandas data analysis engineer.
Generate ONE valid Python Pandas expression using the DataFrame `df` to answer the user's request.

Supported:
- filtering
- column selection
- sorting
- top/bottom N
- max/min row selection
- string matching
- null checks


Rules:
- Return ONLY the expression. No markdown or explanation.
- Use only columns and values supported by the provided schema/data.
- Support filtering, column selection, sorting, and limiting when requested.
- Never modify `df`, access files/network/system resources, import modules, or use eval/exec.
- Never invent columns or values.
- If the request cannot be safely expressed against the schema, return: INVALID_REQUEST
"""


CSV_FILE = Path("data/etl_cache/campaigns.csv")


ALLOWED_ATTRIBUTES = { "loc", "iloc", "str", "contains", "isin", "isna", "notna", "sort_values", "head", "tail" }

DANGEROUS_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.NamedExpr,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
)


def guardrail_expression(expression: str) -> None:
    """Validate LLM-generated Pandas expression before execution."""
    
    df  = load_data(max_rows=5)
    
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return {
            "valid": False,
            "error": "Invalid Pandas expression.",
        }

    for node in ast.walk(tree):

        if type(node) in DANGEROUS_NODES:
            return {
                "valid": False,
                "error": f"Unsafe syntax: {type(node).__name__}",
            }

        if isinstance(node, ast.Name) and node.id != "df":
            return {
                "valid": False,
                "error": f"Unauthorized variable: {node.id}",
            }

        if isinstance(node, ast.Attribute):
            if node.attr not in ALLOWED_ATTRIBUTES:
                return {
                    "valid": False,
                    "error": f"Unauthorized attribute: {node.attr}",
                }

        # Validate df["column"] references.
        if isinstance(node, ast.Subscript):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "df"
                and isinstance(node.slice, ast.Constant)
            ):
                column = node.slice.value

                if isinstance(column, str) and column not in df.columns:
                    return {
                        "valid": False,
                        "error": f"Unknown column: {column}",
                    }

        # Only approved Pandas methods.
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Attribute):
                return {
                    "valid": False,
                    "error": "Function calls are not allowed.",
                }

            if node.func.attr not in ALLOWED_ATTRIBUTES:
                return {
                    "valid": False,
                    "error": f"Unauthorized method: {node.func.attr}",
                }

    return {
        "valid": True,
        "error": "",
    }





def load_data(max_rows: int | None = None) -> pd.DataFrame:
    if not CSV_FILE.exists():
        raise FileNotFoundError(CSV_FILE)

    df = pd.read_csv(CSV_FILE , nrows=max_rows)

    if df.empty:
        raise ValueError("Data is empty.")

    return df


def get_data_context(max_rows: int = 5) -> str:
    """Return first `max_rows` of the campaign CSV as markdown with header."""
    try:
        df  = load_data(max_rows=max_rows)
        try:
            return df.to_markdown(index=False)
        except Exception:
            header = "| " + " | ".join(map(str, df.columns)) + " |"
            sep = "| " + " | ".join(["---"] * len(df.columns)) + " |"
            rows = ["| " + " | ".join(map(str, r)) + " |" for r in df.itertuples(index=False, name=None)]
            return "\n".join([header, sep, *rows])
    except Exception:
        return "Campaign preview unavailable."


def build_pandas_engineer_agent(verbose: bool = False):
    """Build the Pandas Engineer agent."""

    model = agent_factory_model("medium")

    csv_context = get_data_context(max_rows=5)
    system_prompt = (
        f"{PANDAS_ENGINEER_SYSTEM_PROMPT}\n\n"
        f"Allowed methods :\n{ALLOWED_ATTRIBUTES}\n\n"
        f"Data preview (up to 5 rows):\n{csv_context}"
    )

    return create_agent(
        name="Pandas Engineer",
        model=model,
        tools=[],
        debug=verbose,
        system_prompt=system_prompt,
    )


def engineer(message: str, verbose: bool = False) -> str:
    """Run the Pandas engineer agent on a natural-language instruction.

    Args:
        instruction: e.g. "Top 10 products by revenue in 2025".
        verbose: pass True to enable agent debug logging.

    Returns:
        The agent's final answer text (explanation + SQL + results summary).
    """
    agent = build_pandas_engineer_agent(verbose=verbose)
    result = agent.invoke({"messages": [{"role": "user", "content": message}]})

    messages = result.get("messages", [])
    if not messages:
        return "[empty response: agent returned no messages]"

    expression = result["messages"][-1].content
    
    print(expression)
    if expression == "INVALID_REQUEST":
           raise ValueError("Invalid data request.")

    if not expression:
           raise ValueError("Empty model response.")
       
    gurardil_response = guardrail_expression(expression)
    
    if not gurardil_response["valid"]:
        return {
            "error" : gurardil_response["error"],
            "status" : "INVALID_REQUEST"
        }
    
    return  {
        "expression" : expression,
        "status" : "SUCCESS"
    }


        
        
        

        
        
