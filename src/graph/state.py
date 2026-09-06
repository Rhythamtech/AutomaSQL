from typing import TypedDict


class ETLState(TypedDict, total=False):
    data: list[dict]
    transformed_data: list[dict]
    count: int

    question: str
    query_result: object

    is_fresh: bool
    force_refresh: bool

    answer: str
    status: str
    error: str | None
