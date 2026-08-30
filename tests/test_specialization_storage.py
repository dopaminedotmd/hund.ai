import json

import pytest

from hund.specializations.contracts import (
    ConflictState,
    LifecycleState,
    Profile,
    SpecializationManifest,
    SpecializationMembership,
    SpecializationSnapshot,
)
from hund.specializations.storage import StorageConflict, SpecializationStore


def snapshot(version: int = 0) -> SpecializationSnapshot:
    profile = Profile("profile.default", "Default", "global", (), version)
    return SpecializationSnapshot(profile, (), (), (), (), False)


def test_store_round_trips_versioned_snapshot(tmp_path) -> None:
    store = SpecializationStore(tmp_path / "specializations.json")

    new_version = store.save(snapshot(), expected_version=0)
    restored = store.load()

    assert new_version == 1
    assert restored.version == 1
    assert restored.snapshot == snapshot()


def test_compare_and_swap_conflict_does_not_overwrite_previous_state(tmp_path) -> None:
    store = SpecializationStore(tmp_path / "specializations.json")
    store.save(snapshot(), expected_version=0)

    with pytest.raises(StorageConflict) as error:
        store.save(snapshot(), expected_version=0)

    assert error.value.code == "storage_version_conflict"
    assert store.load().version == 1


def test_corrupt_current_state_is_quarantined_and_last_valid_snapshot_survives(tmp_path) -> None:
    path = tmp_path / "specializations.json"
    store = SpecializationStore(path)
    store.save(snapshot(), expected_version=0)
    path.write_text("not-json", encoding="utf-8")

    recovered = store.load()

    assert recovered.version == 1
    assert recovered.snapshot == snapshot()
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    quarantine_files = list((tmp_path / "quarantine").glob("*.json"))
    assert len(quarantine_files) == 1
    quarantined = json.loads(quarantine_files[0].read_text(encoding="utf-8"))
    assert quarantined["reason"] == "corrupt_state"
    assert quarantined["raw"] == "not-json"
