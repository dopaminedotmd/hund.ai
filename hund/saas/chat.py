"""saas_chat — SaaS chat endpoint, pure LLM with no tools.

Uses the same provider client as the agent loop but with a SaaS-specific
system prompt. No tools, no PermissionEngine, no Approval Gate.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ..config import HundConfig
from ..providers.base import Message
from ..providers.openai_compatible import OpenAICompatibleClient
from ..secrets import load_api_key
from .prompt import build_saas_prompt

SAAS_SCHEMA_VERSION = 1


def saas_chat(
    message: str,
    session_id: str | None = None,
    customer_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure LLM chat for SaaS use. No tools, no permissions.

    Args:
        message: User message.
        session_id: Optional session ID for context continuity.
        customer_info: Optional customer details for system prompt.

    Returns:
        Dict with response and session_id.

    Raises:
        RuntimeError: If API key is not configured.
    """
    cfg = HundConfig.load()
    key = load_api_key(cfg.provider.api_key_env)
    if not key:
        raise RuntimeError("HUND_API_KEY not configured — SaaS chat requires an API key")

    client = OpenAICompatibleClient(cfg.provider.base_url, key, cfg.provider.model)

    # Build or load session
    from ..agent import sessions as S

    if session_id:
        session_info = S.info(session_id)
        if not session_info:
            session_id = S.create(title="SaaS Chat")
    else:
        session_id = S.create(title="SaaS Chat")

    # Build messages
    messages: list[Message] = [
        Message(role="system", content=build_saas_prompt(customer_info)),
    ]

    for role, content in S.history(session_id):
        messages.append(Message(role=role, content=content))

    messages.append(Message(role="user", content=message))
    S.add_message(session_id, "user", message)

    # Call LLM — NO tools, pure chat
    result = client.complete(messages, tools=None)

    response = result.text
    S.add_message(session_id, "assistant", response)

    return {
        "response": response,
        "session_id": session_id,
    }
