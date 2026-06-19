from __future__ import annotations

import io
import json
import threading
from contextlib import redirect_stdout

from hund_cli.agent.tui_bridge import TuiBridge


def test_send_keeps_json_on_protocol_stdout_during_agent_redirect() -> None:
    protocol_stdout = io.StringIO()
    agent_stderr = io.StringIO()
    bridge = TuiBridge.__new__(TuiBridge)
    bridge._protocol_stdout = protocol_stdout
    bridge._write_lock = threading.Lock()

    with redirect_stdout(agent_stderr):
        print("agent diagnostic")
        bridge.send("token", text="hund", message_id="msg_1")

    assert agent_stderr.getvalue() == "agent diagnostic\n"
    assert json.loads(protocol_stdout.getvalue()) == {
        "type": "token",
        "text": "hund",
        "message_id": "msg_1",
    }
