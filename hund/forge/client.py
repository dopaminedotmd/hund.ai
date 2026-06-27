"""Client-side submission from Hund to Forge."""
from __future__ import annotations

import json
from typing import Any

import httpx

from ..learning.redactor import redact_text
from .policy import ForgeProposal, idempotency_key


class ForgeSubmitError(RuntimeError):
    pass


def _redact_json(data: Any) -> Any:
    text = json.dumps(data, ensure_ascii=False, sort_keys=True)
    redacted = redact_text(text).text
    try:
        return json.loads(redacted)
    except json.JSONDecodeError as exc:
        raise ForgeSubmitError("redaction produced invalid JSON") from exc


def build_forge_request(
    *,
    tenant_id: str,
    proposal: ForgeProposal | dict[str, Any],
    persona: str = "",
    context: dict[str, Any] | str | None = None,
    simulation_source: bool = False,
) -> dict[str, Any]:
    prop = proposal if isinstance(proposal, ForgeProposal) else ForgeProposal.from_dict(proposal)
    if not tenant_id:
        raise ForgeSubmitError("tenant_id is required")
    if not prop.id:
        raise ForgeSubmitError("proposal.id is required")

    persona_result = redact_text(persona)
    context_obj: Any = context or {}
    if isinstance(context_obj, str):
        context_redacted: Any = redact_text(context_obj).text
    else:
        context_redacted = _redact_json(context_obj)

    return {
        "tenant_id": tenant_id,
        "proposal": _redact_json(prop.to_dict()),
        "persona_redacted": persona_result.text,
        "context_redacted": context_redacted,
        "simulation_source": simulation_source,
    }


def submit_to_forge(
    *,
    endpoint: str,
    service_token: str,
    tenant_id: str,
    proposal: ForgeProposal | dict[str, Any],
    persona: str = "",
    context: dict[str, Any] | str | None = None,
    timeout_s: float = 300.0,
    simulation_source: bool = False,
) -> dict[str, Any]:
    """Submit a redacted proposal to Forge.

    All caller-provided persona/context/proposal data is redacted before network
    I/O. The idempotency key is deterministic per proposal and tenant.
    """
    request = build_forge_request(
        tenant_id=tenant_id,
        proposal=proposal,
        persona=persona,
        context=context,
        simulation_source=simulation_source,
    )
    prop_id = str(request["proposal"]["id"])
    idem = idempotency_key(prop_id, tenant_id)
    headers = {
        "Authorization": f"Bearer {service_token}",
        "Content-Type": "application/json",
        "Idempotency-Key": idem,
    }
    url = endpoint.rstrip("/") + "/forge/evaluate-proposal"
    try:
        response = httpx.post(url, json=request, headers=headers, timeout=timeout_s)
    except httpx.TimeoutException as exc:
        raise ForgeSubmitError("forge_timeout") from exc
    except httpx.HTTPError as exc:
        raise ForgeSubmitError(f"forge_http_error: {exc}") from exc

    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = {"message": response.text}
        raise ForgeSubmitError(str(detail))
    data = response.json()
    if data.get("idempotency_key") != idem:
        raise ForgeSubmitError("idempotency key mismatch")
    return data
