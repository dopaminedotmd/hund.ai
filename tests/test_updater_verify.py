"""Tester för updater-modulen — manifest + SHA256-verifiering.

Alla tester körs offline och deterministiskt.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from hund.updater.manifest import ReleaseManifest
from hund.updater.verify import (
    VerificationError,
    sha256_bytes,
    sha256_file,
    verify_installer,
    verify_manifest,
)


# ------------------------------------------------------------------ #
# Hjälpfunktioner                                                     #
# ------------------------------------------------------------------ #

def _fake_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_tmp(content: bytes) -> Path:
    tmp = Path(tempfile.mktemp(suffix=".ps1"))
    tmp.write_bytes(content)
    return tmp


# ------------------------------------------------------------------ #
# ReleaseManifest                                                     #
# ------------------------------------------------------------------ #

class TestReleaseManifest:
    def _valid(self, **kwargs) -> ReleaseManifest:
        defaults = dict(
            version="0.1.0",
            commit_sha="37947cb1234abcd",
            install_ps1_sha256="a" * 64,
            install_sh_sha256="b" * 64,
            released_at="2026-06-18T00:00:00Z",
            channel="stable",
        )
        defaults.update(kwargs)
        return ReleaseManifest(**defaults)

    def test_valid_manifest_is_valid(self):
        assert self._valid().is_valid()

    def test_missing_version_fails(self):
        m = self._valid(version="")
        assert not m.is_valid()
        assert any("version" in e for e in m.validate())

    def test_short_commit_sha_fails(self):
        m = self._valid(commit_sha="abc")
        assert not m.is_valid()

    def test_wrong_length_sha256_fails_for_stable(self):
        m = self._valid(install_ps1_sha256="tooshort")
        assert not m.is_valid()

    def test_dev_channel_allows_empty_checksums(self):
        m = self._valid(channel="dev", install_ps1_sha256="", install_sh_sha256="")
        # dev-kanal: checksums är valfria
        errs = m.validate()
        sha_errs = [e for e in errs if "sha256" in e.lower()]
        assert sha_errs == [], f"dev-kanal ska inte kräva sha256: {errs}"

    def test_unknown_channel_fails(self):
        m = self._valid(channel="nightly")
        errors = m.validate()
        assert any("kanal" in e for e in errors)

    def test_roundtrip_json(self):
        m = self._valid()
        m2 = ReleaseManifest.from_json(m.to_json())
        assert m == m2

    def test_from_dict_roundtrip(self):
        m = self._valid()
        m2 = ReleaseManifest.from_dict(m.to_dict())
        assert m == m2


# ------------------------------------------------------------------ #
# sha256_file / sha256_bytes                                          #
# ------------------------------------------------------------------ #

class TestSha256:
    def test_sha256_bytes_known(self):
        data = b"hund"
        expected = hashlib.sha256(data).hexdigest()
        assert sha256_bytes(data) == expected

    def test_sha256_file_matches_bytes(self, tmp_path):
        p = tmp_path / "test.bin"
        data = b"hund_test_content"
        p.write_bytes(data)
        assert sha256_file(p) == sha256_bytes(data)

    def test_sha256_empty_file(self, tmp_path):
        p = tmp_path / "empty.txt"
        p.write_bytes(b"")
        assert sha256_file(p) == hashlib.sha256(b"").hexdigest()


# ------------------------------------------------------------------ #
# verify_installer                                                    #
# ------------------------------------------------------------------ #

class TestVerifyInstaller:
    def test_correct_checksum_passes(self, tmp_path):
        content = b"Write-Host 'hund'\n"
        p = tmp_path / "install.ps1"
        p.write_bytes(content)
        expected = sha256_bytes(content)
        assert verify_installer(p, expected) is True

    def test_wrong_checksum_raises(self, tmp_path):
        p = tmp_path / "install.ps1"
        p.write_bytes(b"Write-Host 'hund'\n")
        with pytest.raises(VerificationError, match="SHA256-mismatch"):
            verify_installer(p, "a" * 64)

    def test_wrong_checksum_no_raise(self, tmp_path):
        p = tmp_path / "install.ps1"
        p.write_bytes(b"Write-Host 'hund'\n")
        result = verify_installer(p, "a" * 64, raise_on_fail=False)
        assert result is False

    def test_missing_file_raises(self, tmp_path):
        p = tmp_path / "nonexistent.ps1"
        with pytest.raises(VerificationError, match="hittades ej"):
            verify_installer(p, "a" * 64)

    def test_missing_file_no_raise(self, tmp_path):
        p = tmp_path / "nonexistent.ps1"
        assert verify_installer(p, "a" * 64, raise_on_fail=False) is False

    def test_checksum_case_insensitive(self, tmp_path):
        content = b"content"
        p = tmp_path / "install.sh"
        p.write_bytes(content)
        expected_lower = sha256_bytes(content)
        expected_upper = expected_lower.upper()
        assert verify_installer(p, expected_upper) is True


# ------------------------------------------------------------------ #
# verify_manifest                                                     #
# ------------------------------------------------------------------ #

class TestVerifyManifest:
    def test_dev_channel_skips_file_checksums(self, tmp_path):
        """Dev-manifest behöver inte ha giltiga SHA256 för filerna."""
        m = ReleaseManifest(
            version="0.2.0-dev",
            commit_sha="abc1234",
            install_ps1_sha256="",
            install_sh_sha256="",
            released_at="2026-06-18T00:00:00Z",
            channel="dev",
        )
        errors = verify_manifest(m, tmp_path)
        # inga fel för dev-kanal (filer behöver inte ens finnas)
        file_errors = [e for e in errors if "sha256" in e.lower() or "hittades" in e]
        assert file_errors == []

    def test_stable_channel_detects_checksum_mismatch(self, tmp_path):
        content = b"#!/bin/bash\necho hund\n"
        ps1 = tmp_path / "install.ps1"
        sh = tmp_path / "install.sh"
        correct = sha256_bytes(content)
        ps1.write_bytes(content)
        sh.write_bytes(content)

        m = ReleaseManifest(
            version="0.1.0",
            commit_sha="37947cb",
            install_ps1_sha256="a" * 64,  # fel checksumma
            install_sh_sha256=correct,
            released_at="2026-06-18T00:00:00Z",
            channel="stable",
        )
        errors = verify_manifest(m, tmp_path)
        assert any("SHA256-mismatch" in e or "ps1" in e.lower() for e in errors)

    def test_stable_channel_passes_with_correct_checksums(self, tmp_path):
        content = b"#!/bin/bash\necho hund\n"
        ps1 = tmp_path / "install.ps1"
        sh = tmp_path / "install.sh"
        digest = sha256_bytes(content)
        ps1.write_bytes(content)
        sh.write_bytes(content)

        m = ReleaseManifest(
            version="0.1.0",
            commit_sha="37947cb",
            install_ps1_sha256=digest,
            install_sh_sha256=digest,
            released_at="2026-06-18T00:00:00Z",
            channel="stable",
        )
        errors = verify_manifest(m, tmp_path)
        assert errors == []
