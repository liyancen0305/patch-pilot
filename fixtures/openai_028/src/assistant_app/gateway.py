from typing import Any

import openai


def complete(prompt: str, gateway: Any = None) -> str:
    api = gateway or openai.ChatCompletion
    response = api.create(model="gpt-3.5-turbo",
                          messages=[{"role": "user", "content": prompt}])
    return str(response["choices"][0]["message"]["content"])
