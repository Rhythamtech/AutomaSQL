import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from src.agents.base import agent_factory_model
from config.constant import DATA_ANALYSIS_SYSTEM_PROMPT

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
