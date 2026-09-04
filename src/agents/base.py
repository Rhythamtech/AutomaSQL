import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from typing_extensions import Literal

load_dotenv()


def agent_factory_model(level:Literal["high", "medium", "low"]) -> ChatOpenAI:
    model = ChatOpenAI(
                base_url=os.getenv("OPENAI_BASE_URL"),
                api_key=os.getenv("OPENAI_API_KEY"),
                model=os.getenv(f"OPENAI_MODEL_{level.upper()}"),
                temperature=0.7,
                # Router (sslip.io) returns SSE chunks even for non-streaming
                # calls. With streaming=False, invoke() parses to empty "".
                # streaming=True aggregates stream chunks, invoke() -> "OK".
                streaming=True,
            )
    
    return model
