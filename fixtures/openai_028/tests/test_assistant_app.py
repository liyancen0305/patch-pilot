from types import SimpleNamespace
from typing import Any

from assistant_app import summarize


class Reply(dict[str, Any]):
    def __init__(self, text: str) -> None:
        super().__init__(choices=[{"message": {"content": text}}])
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=text))]


class FakeGateway:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=self)
        self.messages: list[dict[str, str]] = []

    def create(self, *, model: str, messages: list[dict[str, str]]) -> Reply:
        assert model == "gpt-3.5-turbo"
        self.messages = messages
        return Reply("  concise summary  ")


def test_summarize_preserves_prompt_and_output() -> None:
    fake = FakeGateway()
    assert summarize("  migration  ", gateway=fake) == "concise summary"
    assert fake.messages == [{"role": "user", "content": "Summarize migration"}]
