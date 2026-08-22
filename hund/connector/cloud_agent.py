"""CloudAgent — connector-side communication with cloud orchestration server.

Handles registration, heartbeat (background thread), event forwarding,
and receiving deployed intents.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


CLOUD_AGENT_VERSION = "1.0.0"
_HEARTBEAT_INTERVAL_S = 30


@dataclass
class CloudConfig:
    url: str = ""
    connector_id: str = ""
    api_key: str = ""


class CloudAgent:
    """Manages cloud communication for a connector.

    Args:
        config: CloudConfig with url, connector_id, api_key.
        auto_heartbeat: Start background heartbeat thread (default True).
    """

    def __init__(self, config: CloudConfig, auto_heartbeat: bool = True) -> None:
        self._config = config
        self._running = False
        self._thread: threading.Thread | None = None
        self._events_queue: list[dict[str, Any]] = []

        if auto_heartbeat:
            self.start_heartbeat()

    # ── Registration ───────────────────────────────────────────────

    def register(self, hostname: str = "", version: str = "0.0.0") -> bool:
        """Register this connector with the cloud server.

        Args:
            hostname: Machine hostname.
            version: Connector version.

        Returns:
            True if registration succeeded.
        """
        import socket
        hostname = hostname or socket.gethostname()

        body = json.dumps({
            "connector_id": self._config.connector_id,
            "hostname": hostname,
            "version": version,
            "public_key": "",
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{self._config.url}/cloud/register",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
            if resp.get("status") == "registered":
                self._config.connector_id = resp.get("connector_id", self._config.connector_id)
                self._config.api_key = resp.get("api_key", "")
                return True
            return False
        except Exception:
            return False

    def deregister(self) -> bool:
        """Deregister this connector from the cloud."""
        if not self._config.api_key:
            return False

        try:
            req = urllib.request.Request(
                f"{self._config.url}/cloud/connectors/{self._config.connector_id}",
                method="DELETE",
                headers={"Authorization": f"Bearer {self._config.api_key}"},
            )
            urllib.request.urlopen(req, timeout=10)
            return True
        except Exception:
            return False

    # ── Heartbeat ──────────────────────────────────────────────────

    def start_heartbeat(self) -> None:
        """Start background heartbeat thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()

    def stop_heartbeat(self) -> None:
        """Stop the heartbeat thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _heartbeat_loop(self) -> None:
        """Send heartbeat every 30 seconds."""
        while self._running:
            try:
                self._send_heartbeat()
            except Exception:
                pass
            time.sleep(_HEARTBEAT_INTERVAL_S)

    def _send_heartbeat(self) -> None:
        """Send a single heartbeat."""
        if not self._config.api_key:
            return
        body = json.dumps({
            "connector_id": self._config.connector_id,
            "status": "online",
            "load": 0,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self._config.url}/cloud/heartbeat",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._config.api_key}",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)

    # ── Event forwarding ───────────────────────────────────────────

    def forward_event(self, event: dict[str, Any]) -> None:
        """Forward a trace event to the cloud (non-blocking)."""
        if not self._config.api_key:
            return

        body = json.dumps({
            "connector_id": self._config.connector_id,
            "event": event,
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{self._config.url}/cloud/events",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._config.api_key}",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # Best-effort

    # ── Properties ─────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return bool(self._config.api_key)

    @property
    def cloud_url(self) -> str:
        return self._config.url

    @property
    def connector_id(self) -> str:
        return self._config.connector_id

    @classmethod
    def from_env(cls, auto_heartbeat: bool = True) -> CloudAgent | None:
        """Create CloudAgent from HUND_CLOUD_URL and HUND_CLOUD_CONNECTOR_ID env vars."""
        url = os.environ.get("HUND_CLOUD_URL", "")
        cid = os.environ.get("HUND_CLOUD_CONNECTOR_ID", "")
        api_key = os.environ.get("HUND_CLOUD_API_KEY", "")
        if not url:
            return None
        return cls(CloudConfig(url=url, connector_id=cid, api_key=api_key), auto_heartbeat=auto_heartbeat)
