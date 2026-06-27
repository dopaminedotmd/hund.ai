"""Forge training v2 contract, apply-policy, and isolation tests."""

from __future__ import annotations

import socket
from threading import Thread

import httpx
import pytest

from hund.cloud.server import CloudServer
from hund.forge.client import build_forge_request
from hund.forge.policy import ForgeProposal, classify_artifact, evaluate_proposal_locally
from hund.forge.registry import ForgeRegistry


def _proposal(**overrides) -> ForgeProposal:
    data = {
        "id": "p1",
        "title": "Excel skill",
        "problem": "Missade pivottabeller tre gånger",
        "proposed_change": "Lägg till tenant-local Excel skill",
        "change_type": "skill",
        "risk": "low",
        "evidence": ("gap-1", "gap-2"),
    }
    data.update(overrides)
    return ForgeProposal(**data)


def test_tcb_target_blocks_before_staging():
    proposal = _proposal(
        proposed_change="Ändra hund/agent/safety.py för att tillåta skrivning",
        change_type="skill",
    )
    decision = classify_artifact(proposal)
    assert decision.state == "blocked_tcb"
    assert decision.policy.auto_stage is False
    assert decision.policy.auto_promote is False

    evaluation = evaluate_proposal_locally(proposal, tenant_id="tenant-1")
    assert evaluation.verdict == "rejected"
    assert evaluation.state == "blocked_tcb"


def test_tenant_local_low_risk_auto_promotes(tmp_path):
    registry = ForgeRegistry(tmp_path / "hund.db")
    proposal = _proposal()
    evaluation = evaluate_proposal_locally(proposal, tenant_id="tenant-1")
    artifact = registry.stage_verified(
        tenant_id="tenant-1",
        proposal=proposal,
        evaluation=evaluation,
        payload={"proposal": proposal.to_dict(), "secret": "sk-my-long-enough-secret-key"},
    )
    assert artifact["artifact_type"] == "tenant-local-skill"
    assert artifact["state"] == "promoted"
    assert artifact["scope"] == "tenant"
    assert "sk-my-long-enough-secret-key" not in str(artifact["payload_redacted"])


def test_shared_or_prompt_artifact_needs_review(tmp_path):
    registry = ForgeRegistry(tmp_path / "hund.db")
    proposal = _proposal(change_type="prompt", risk="low")
    evaluation = evaluate_proposal_locally(proposal, tenant_id="tenant-1")
    artifact = registry.stage_verified(
        tenant_id="tenant-1",
        proposal=proposal,
        evaluation=evaluation,
        payload={"proposal": proposal.to_dict()},
    )
    assert artifact["artifact_type"] == "prompt-persona"
    assert artifact["state"] == "needs_review"
    assert artifact["apply_policy"]["auto_promote"] is False


def test_simulation_artifacts_are_filterable(tmp_path):
    registry = ForgeRegistry(tmp_path / "hund.db")
    proposal = _proposal(id="sim-1")
    evaluation = evaluate_proposal_locally(proposal, tenant_id="tenant-1")
    registry.stage_verified(
        tenant_id="tenant-1",
        proposal=proposal,
        evaluation=evaluation,
        payload={"proposal": proposal.to_dict()},
        source="simulation",
    )
    assert len(registry.list_artifacts(include_simulation=True)) == 1
    assert registry.list_artifacts(include_simulation=False) == []


def test_revoke_training_mandate_moves_tenant_artifacts_to_review(tmp_path):
    registry = ForgeRegistry(tmp_path / "hund.db")
    proposal = _proposal()
    evaluation = evaluate_proposal_locally(proposal, tenant_id="tenant-1")
    registry.stage_verified(
        tenant_id="tenant-1",
        proposal=proposal,
        evaluation=evaluation,
        payload={"proposal": proposal.to_dict()},
    )
    assert registry.revoke_training_mandate("tenant-1") == 1
    artifact = registry.list_artifacts(tenant_id="tenant-1")[0]
    assert artifact["state"] == "needs_review"


def test_build_forge_request_redacts_before_network():
    request = build_forge_request(
        tenant_id="tenant-1",
        proposal=_proposal(),
        persona="User lives at C:\\Users\\William and token sk-my-long-enough-secret-key",
        context={"raw": "Contact william@example.com"},
    )
    serialized = str(request)
    assert "sk-my-long-enough-secret-key" not in serialized
    assert "william@example.com" not in serialized
    assert "C:\\Users\\William" not in serialized


@pytest.fixture
def forge_server(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("HUND_FORGE_SERVICE_TOKEN", "test-token")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = CloudServer(port=port, bind="127.0.0.1")

    def serve():
        while not getattr(server, "_stop", False):
            server.handle_request()
        server.server_close()

    thread = Thread(target=serve, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server._stop = True
    try:
        httpx.get(f"http://127.0.0.1:{port}/cloud/health", timeout=1)
    except Exception:
        pass
    thread.join(timeout=2)


def test_forge_endpoint_evaluates_and_caches(forge_server):
    request = {
        "tenant_id": "tenant-1",
        "proposal": _proposal().to_dict(),
        "persona_redacted": "hund",
        "context_redacted": {},
        "simulation_source": False,
    }
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": "idem-1",
    }
    first = httpx.post(
        f"{forge_server}/forge/evaluate-proposal",
        json=request,
        headers=headers,
        timeout=5,
    )
    second = httpx.post(
        f"{forge_server}/forge/evaluate-proposal",
        json=request,
        headers=headers,
        timeout=5,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["artifact"]["state"] == "promoted"


def test_forge_endpoint_requires_service_token(forge_server):
    resp = httpx.post(
        f"{forge_server}/forge/evaluate-proposal",
        json={"tenant_id": "tenant-1", "proposal": _proposal().to_dict()},
        headers={"Authorization": "Bearer wrong"},
        timeout=5,
    )
    assert resp.status_code == 401
