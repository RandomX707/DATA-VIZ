from __future__ import annotations

from openai import OpenAI

from config import config


def get_client() -> OpenAI:
    """Return an OpenAI-compatible client pointed at LiteLLM."""
    if not config.LITELLM_API_KEY:
        raise RuntimeError(
            "LITELLM_API_KEY is not set. "
            "Add it to your .env file or pass it as LITELLM_API_KEY=... before the command."
        )
    if not config.LITELLM_BASE_URL:
        raise RuntimeError(
            "LITELLM_BASE_URL is not set. "
            "Set it to your LiteLLM proxy URL, e.g. https://litellm.yourcompany.com"
        )
    return OpenAI(
        api_key=config.LITELLM_API_KEY,
        base_url=config.LITELLM_BASE_URL,
    )


def chat(system: str, user: str, max_tokens: int | None = None) -> str:
    """Single LLM call. Returns the text content of the first choice."""
    client = get_client()
    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        max_tokens=max_tokens or config.LLM_MAX_TOKENS,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content or ""
