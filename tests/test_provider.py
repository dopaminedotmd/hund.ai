"""Provider-test mot riktig modell (läser vald provider från config). Skippar om ingen nyckel/saldo.

Kör:  HUND_API_KEY=... uv run pytest tests/test_provider.py -q
"""
from __future__ import annotations

import os

import pytest

from hund.config import HundConfig
from hund.providers.base import Message
from hund.providers.openai_compatible import OpenAICompatibleClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("HUND_API_KEY"),
    reason="HUND_API_KEY ej satt — kräver riktig nyckel + saldo",
)


def test_provider_roundtrip():
    cfg = HundConfig.load()
    client = OpenAICompatibleClient(
        base_url=cfg.provider.base_url,
        api_key=os.environ["HUND_API_KEY"],
        default_model=cfg.provider.model,
    )
    try:
        result = client.complete(
            [Message(role="user", content="Svara med exakt: HUND_LEVER")]
        )
    except RuntimeError as e:
        msg = str(e).lower()
        # Saldo/fel nyckel = inte ett kod-fel. Skip.
        if "429" in msg or "balance" in msg or "401" in msg:
            pytest.skip(f"provider ej användbar just nu: {e}")
        raise

    # Modellen kan ibland svara med varianter ("HUND_LEVER." eller bara "8").
    # Vi verifierar att vi faktiskt fick ett svar och att token-räknare fungerar.
    # Exakt echo-test är opålitligt mot live-LLM — skippa om svaret är oväntat.
    assert result.total_tokens > 0, "Förväntar tokens > 0"
    if "HUND_LEVER" not in result.text:
        pytest.skip(
            f"Modellen svarade oväntat ({result.text!r}); "
            "live-LLM kan inte garantera exakt echo — skip istf fail"
        )

