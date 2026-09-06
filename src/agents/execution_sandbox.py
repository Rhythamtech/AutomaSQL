import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from src.agents.base import agent_factory_model




DATA_ANALYSIS_SYSTEM_PROMPT = """You are a data analyst.

Answer the user's question using ONLY the provided Data result.

Rules:
- Give the direct answer to the user's question.
- Use only facts supported by the dataframe result.
- Do not invent, assume, or estimate missing information.
- If the result is empty or does not contain enough information, clearly say that the data is insufficient.
- Preserve exact values from the result.
- For numeric answers, include appropriate units when available.
- Keep the response concise and easy to understand.
- Do not mention Pandas, Python, AST, guardrails, expressions, or internal processing.
- Do not explain how the answer was calculated unless the user asks.
- If multiple rows/items are relevant, present them clearly as a short list or table.

Provide the final answer to the user."""

def analyzer_agent(question,context):
    agent = agent_factory_model("high")
    if hasattr(context, "to_string"):
        try:
            context_str = context.to_string(index=False)
        except Exception:
            context_str = str(context)
    else:
        context_str = str(context)

    result = agent.invoke(
        [
            SystemMessage(content=DATA_ANALYSIS_SYSTEM_PROMPT),
            HumanMessage(content=f"Question: {question}\nContext: {context_str}"),
        ]
    )

    return result.content
    


def execute_safe(expression: str, df: pd.DataFrame):
    # validate pandas expression
    # validate sql query

    return eval(
        expression,
        {"__builtins__": {}},
        {"df": df},
    )
