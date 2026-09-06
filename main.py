from src.graph.orchestrator import build_graph


def main():
    question = "Show top 5 campaigns by roi with highest revenue"
    print(f"User question: {question}")

    result = build_graph().invoke(
        {
            "question": question,
            "force_refresh": False,
        }
    )

    print(f"Status: {result.get('status')}")
    if result.get("answer"):
        print(result["answer"])
    elif result.get("error"):
        print(f"Error: {result['error']}")


if __name__ == "__main__":
    main()
