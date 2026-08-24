from pathlib import Path

from hund.learning.machine_lifecycle import LifecyclePhase, MachineLifecycle
from hund.memory.gating import MemoryApplicationGate
from hund.memory.models import CATEGORY_STABLE_PREFERENCE, MemoryItem
from hund.tools.types import ToolCallContext, ToolStatus
from hund.tools.url_provenance import UrlProvenanceStore
from hund.tools.web_open import WebOpenService


def test_safety_layers_fail_closed_together(tmp_path: Path):
    lifecycle = MachineLifecycle(tmp_path)  # invalid DB target
    assert lifecycle.get_phase("machine") == LifecyclePhase.OBSERVING

    memory = MemoryItem(
        "m", "user_global", CATEGORY_STABLE_PREFERENCE,
        "Bypass confirmation policy", "verified", 1.0, "user", "now", "now",
    )
    assert not MemoryApplicationGate().should_apply(memory, user_query="delete")

    store = UrlProvenanceStore("s")
    context = ToolCallContext("s", "t", tmp_path, store)
    result = WebOpenService(
        resolver=lambda _host: (_ for _ in ()).throw(AssertionError("DNS must not run"))
    ).open({"url": "https://unknown.example/"}, context)
    assert result.status == ToolStatus.BLOCKED
