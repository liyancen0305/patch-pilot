from typing import Any

from .gateway import complete


def summarize(topic: str, gateway: Any = None) -> str:
    return complete(f"Summarize {topic.strip()}", gateway=gateway).strip()
