from pathlib import Path

from hund.paths import config_path, hund_home, memory_db_path, requests_db_path


def test_hund_home_environment_override_is_the_complete_data_root(
    monkeypatch, tmp_path: Path
) -> None:
    private_home = tmp_path / "private-hund"
    monkeypatch.setenv("HUND_HOME", str(private_home))

    assert hund_home() == private_home
    assert config_path() == private_home / "config.json"
    assert memory_db_path() == private_home / "memory" / "memory.db"
    assert requests_db_path() == private_home / "logs" / "requests.db"
