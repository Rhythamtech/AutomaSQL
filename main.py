from src.agents.sql_engineer import build_schema_context, engineer
from src.agents.etl_architect import build_graph

def main():
   # print(build_schema_context())
    question = "Show top 5 campaigns by roi with highest revenue"
    print(f"User question: {question}")
    pipeline = build_graph()
    
    result = pipeline.invoke({})

    print(f"Status: {result['status']}")
    print(f"Records fetched: {result['count']}")


if __name__ == "__main__":
    main()
