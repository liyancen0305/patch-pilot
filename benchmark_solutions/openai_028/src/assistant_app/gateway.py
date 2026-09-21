from typing import Any

from openai import OpenAI


def complete(prompt: str, gateway: Any = None) -> str:
    client = gateway or OpenAI()
    response = client.chat.completions.create(
        model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}])
    return str(response.choices[0].message.content)
