"""Shared Chat Completions transport: streaming, provider options and timings."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from urllib.parse import urlsplit

import httpx


logger = logging.getLogger(__name__)
TextCallback = Callable[[str], None]


class CompletionError(RuntimeError):
    """An unsuccessful or incomplete model response."""


async def _events(response: httpx.Response) -> AsyncIterator[str]:
    """Decode SSE frames independently of TCP chunks, ignoring keepalives."""
    data: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if data:
                yield "\n".join(data)
                data.clear()
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    if data:
        yield "\n".join(data)


async def complete(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    client_factory: Callable[..., httpx.AsyncClient],
    temperature: float,
    thinking: str,
    stream: bool,
    on_delta: TextCallback | None,
    label: str,
) -> str:
    missing = [name for name, value in {
        "BASE_URL": base_url, "API_KEY": api_key, "MODEL": model,
    }.items() if not value]
    if missing:
        raise CompletionError(f"Missing .env configuration: {', '.join(missing)}")
    payload = {"model": model, "messages": messages, "temperature": temperature}
    if urlsplit(base_url).hostname == "api.deepseek.com" and model.startswith("deepseek-v4-"):
        if thinking not in ("enabled", "disabled", "default"):
            raise CompletionError("DeepSeek thinking must be enabled, disabled or default.")
        if thinking != "default":
            payload["thinking"] = {"type": thinking}
    streaming = stream and on_delta is not None
    payload["stream"] = streaming
    request_id = uuid.uuid4().hex[:8]
    started = time.perf_counter()
    first_reasoning = False
    first_text = False
    parts: list[str] = []
    status = "failed"

    def accept(text: str) -> None:
        nonlocal first_text
        if not isinstance(text, str):
            raise CompletionError("API returned invalid text content.")
        if not text:
            return
        if not first_text:
            first_text = True
            logger.info("API %s %s first_text_s=%.3f", request_id, label, time.perf_counter() - started)
        parts.append(text)
        if on_delta is not None:
            on_delta(text)

    logger.info("API %s %s started stream=%s", request_id, label, streaming)
    try:
        # Each worker owns an asyncio loop: do not share an AsyncClient across loops.
        async with client_factory(timeout=45.0) as client:
            async with client.stream(
                "POST", f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"}, json=payload,
            ) as response:
                if response.is_error:
                    raise CompletionError(f"API HTTP {response.status_code}")
                logger.info("API %s %s headers_s=%.3f", request_id, label, time.perf_counter() - started)
                if not streaming or "application/json" in response.headers.get("content-type", ""):
                    await response.aread()
                    choice = response.json()["choices"][0]
                    if choice.get("finish_reason") not in (None, "stop"):
                        raise CompletionError(f"API response incomplete: {choice['finish_reason']}")
                    accept(choice["message"]["content"])
                else:
                    finished = False
                    async for event in _events(response):
                        if event == "[DONE]":
                            finished = True
                            break
                        chunk = json.loads(event)
                        if "error" in chunk:
                            raise CompletionError("API reported an error during streaming.")
                        choices = chunk.get("choices", [])
                        if not choices:  # usage-only chunks
                            continue
                        choice = choices[0]
                        delta = choice.get("delta", {})
                        if delta.get("reasoning_content") and not first_reasoning:
                            first_reasoning = True
                            logger.info("API %s %s first_reasoning_s=%.3f", request_id, label, time.perf_counter() - started)
                        if delta.get("content") is not None:
                            accept(delta["content"])
                        reason = choice.get("finish_reason")
                        if reason is not None:
                            if reason != "stop":
                                raise CompletionError(f"API response incomplete: {reason}")
                            finished = True
                    if not finished:
                        raise CompletionError("API stream ended before completion; please retry.")
        result = "".join(parts).strip()
        if not result:
            raise CompletionError("API returned empty text.")
        status = "ok"
        return result
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    except httpx.HTTPError as error:
        # Do not log response bodies, authorization headers or selected text.
        raise CompletionError(f"API request failed: {type(error).__name__}") from error
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise CompletionError("API returned an unexpected response.") from error
    finally:
        logger.info("API %s %s total_s=%.3f status=%s", request_id, label, time.perf_counter() - started, status)
