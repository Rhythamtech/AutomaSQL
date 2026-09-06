import logging

from langgraph.graph import END, START, StateGraph

from src.graph.nodes import (
    answer,
    check_data_freshness,
    execute_sql,
    fetch_data,
    query_campaigns,
    query_sql,
    route_after_freshness,
    route_after_question,
    route_question,
    save_to_csv,
    transform_data,
)
from src.graph.state import ETLState


def build_graph():
    graph = StateGraph(ETLState)

    graph.add_node("route_question", route_question)
    graph.add_node("check_freshness", check_data_freshness)
    graph.add_node("fetch", fetch_data)
    graph.add_node("transform", transform_data)
    graph.add_node("save", save_to_csv)
    graph.add_node("query_pandas", query_campaigns)
    graph.add_node("query_sql", query_sql)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("answer", answer)

    graph.add_edge(START, "route_question")
    graph.add_conditional_edges(
        "route_question",
        route_after_question,
        {
            "sql": "query_sql",
            "pandas": "check_freshness",
        },
    )
    graph.add_conditional_edges(
        "check_freshness",
        route_after_freshness,
        {
            "query_pandas": "query_pandas",
            "fetch": "fetch",
        },
    )
    graph.add_edge("fetch", "transform")
    graph.add_edge("transform", "save")
    graph.add_edge("save", "query_pandas")
    graph.add_edge("query_pandas", "answer")
    graph.add_edge("query_sql", "execute_sql")
    graph.add_edge("execute_sql", "answer")
    graph.add_edge("answer", END)

    return graph.compile()


def build_etl_graph():
    return build_graph()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    question = "Which campaign generated the most revenue?"
    result = build_graph().invoke(
        {
            "question": question,
            "force_refresh": False,
        }
    )

    print(result.get("answer", result.get("error", result.get("status"))))


if __name__ == "__main__":
    main()
