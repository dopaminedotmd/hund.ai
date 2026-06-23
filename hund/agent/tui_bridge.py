"""JSON-lines IPC bridge between OpenTUI and the existing Hund agent loop."""
from __future__ import annotations

import json
import re
import sys
import threading
import uuid
from contextlib import redirect_stdout
from typing import Any, TextIO

from rich.console import Console

from ..providers.base import Message
from .context import maybe_compress
from .loop import (
    _agent_turn,
    _init_runtime,
    _session_save,
    assemble_system_prompt,
)


class TuiBridge:
    """Serve newline-delimited JSON on stdin/stdout."""

    def __init__(self) -> None:
        # Keep the protocol stream stable. redirect_stdout() replaces sys.stdout
        # process-wide, including while sink callbacks emit IPC events.
        self._protocol_stdout: TextIO = sys.stdout
        self._write_lock = threading.Lock()
        self._turn_lock = threading.Lock()
        self._approval_condition = threading.Condition()
        self._approvals: dict[str, bool] = {}
        self._active_tool_call_id: str | None = None
        self._message_id: str | None = None
        self._message_parts: list[str] = []
        self._tasks: list[dict[str, str]] = []
        self._active_task_id: str | None = None
        self._current_request = ""
        self._files_edited = 0
        self._shutdown = False
        self.console = Console(stderr=True)
        with redirect_stdout(sys.stderr):
            self.runtime = _init_runtime()

    def send(self, event_type: str, **payload: Any) -> None:
        line = json.dumps(
            {"type": event_type, **payload},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._write_lock:
            self._protocol_stdout.write(line + "\n")
            self._protocol_stdout.flush()

    def run(self) -> int:
        self._send_task_list()
        self._send_stats()
        if not self.runtime.key:
            self.send(
                "error",
                message=(
                    "API key missing. Configure "
                    f"{self.runtime.cfg.provider.api_key_env} with `hund setup`."
                ),
            )

        for raw_line in sys.stdin:
            if self._shutdown:
                break
            line = raw_line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
                self.handle_message(message)
            except json.JSONDecodeError as exc:
                self.send("error", message=f"Invalid JSON: {exc.msg}")
            except Exception as exc:
                self.send("error", message=str(exc))
        return 0

    def handle_message(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "user_input":
            text = str(message.get("text", "")).strip()
            if text:
                threading.Thread(
                    target=self._process_user_input,
                    args=(text,),
                    daemon=True,
                ).start()
            return
        if message_type == "tool_approval":
            tool_call_id = str(message.get("tool_call_id", ""))
            with self._approval_condition:
                self._approvals[tool_call_id] = bool(message.get("approved"))
                self._approval_condition.notify_all()
            return
        if message_type == "command":
            self._handle_command(str(message.get("command", "")))
            return
        self.send("error", message=f"Unknown message type: {message_type}")

    def _process_user_input(self, text: str) -> None:
        if not self._turn_lock.acquire(blocking=False):
            self.send("error", message="Agent is already processing a request.")
            return
        try:
            if not self.runtime.key:
                return
            self._start_turn_tasks(text)
            rt = self.runtime
            rt.messages.append(Message(role="user", content=text))
            _session_save(rt.session_id, "user", text)
            rt.messages[0] = Message(
                role="system",
                content=assemble_system_prompt(
                    rt.persona,
                    rt.profile,
                    knowledge=rt.knowledge,
                    policy_rules=rt.policy_rules,
                    skills=rt.skills,
                    user_text=text,
                    memory_lines=rt.memory_lines,
                ),
            )
            compressed = maybe_compress(rt.messages)
            if compressed.compressed:
                rt.messages[:] = compressed.messages

            with redirect_stdout(sys.stderr):
                _agent_turn(
                    self.console,
                    rt.client,
                    rt.messages,
                    rt.schemas,
                    rt.engine,
                    rt.cfg,
                    rt.session_id,
                    sink=self,
                )
            self._complete_turn_tasks()
            self.send("status", state="idle")
        except Exception as exc:
            self.send("error", message=str(exc))
            self.send("status", state="error")
        finally:
            self._send_stats()
            self._turn_lock.release()

    def _handle_command(self, command: str) -> None:
        if command == "exit":
            self._shutdown = True
            with self._approval_condition:
                self._approval_condition.notify_all()
        elif command == "interrupt":
            self.send("error", message="Interrupt requested.")
            self.send("status", state="idle")
        elif command == "stats":
            self._send_stats()
        else:
            self.send("error", message=f"Unknown command: {command}")

    def _send_stats(self) -> None:
        if not self.runtime.key:
            context_pct = 0
        else:
            characters = sum(
                len(message.content or "") for message in self.runtime.messages
            )
            context_pct = min(100, round(characters / 320))
        self.send(
            "stats",
            context_pct=context_pct,
            files_edited=self._files_edited,
        )

    def _send_task_list(self) -> None:
        self.send("task_list", tasks=[dict(task) for task in self._tasks])

    def _start_turn_tasks(self, text: str) -> None:
        self._current_request = text
        self._active_task_id = None
        self._tasks = [
            {
                "id": f"task_{uuid.uuid4().hex}",
                "text": text,
                "status": "pending",
            }
        ]
        self._send_task_list()

    def _start_tool_task(self, name: str, args: dict[str, Any]) -> None:
        task = next(
            (task for task in self._tasks if task["status"] == "pending"),
            None,
        )
        if task is None:
            task = {
                "id": f"task_{uuid.uuid4().hex}",
                "text": self._tool_task_text(name, args),
                "status": "pending",
            }
            self._tasks.append(task)
        elif task["text"] == self._current_request:
            task["text"] = self._tool_task_text(name, args)
        task["status"] = "in_progress"
        self._active_task_id = task["id"]
        self._send_task_list()

    def _complete_active_task(self) -> None:
        if self._active_task_id is None:
            return
        for task in self._tasks:
            if task["id"] == self._active_task_id:
                task["status"] = "completed"
                break
        self._active_task_id = None
        self._send_task_list()

    def _complete_turn_tasks(self) -> None:
        changed = False
        for task in self._tasks:
            if task["status"] != "completed":
                task["status"] = "completed"
                changed = True
        self._active_task_id = None
        if changed:
            self._send_task_list()

    @staticmethod
    def _tool_task_text(name: str, args: dict[str, Any]) -> str:
        path = args.get("path")
        if isinstance(path, str) and path:
            return f"{name}: {path}"
        command = args.get("command")
        if isinstance(command, str) and command:
            return f"{name}: {command}"
        return name

    # Agent sink protocol -------------------------------------------------
    def thinking(self, msg: str | None = None) -> None:
        self._message_id = None
        self._message_parts = []
        self.send("status", state="thinking")

    def clear_thinking(self) -> None:
        self.send("status", state="streaming")

    def chunk(self, text: str) -> None:
        if self._message_id is None:
            self._message_id = f"msg_{uuid.uuid4().hex}"
        self._message_parts.append(text)
        self.send("token", text=text, message_id=self._message_id)

    def end_assistant(self) -> None:
        if self._message_id is None:
            return
        self.send(
            "token_done",
            message_id=self._message_id,
            full_text="".join(self._message_parts),
        )

    def error(self, markup: str) -> None:
        clean = re.sub(r"\[/?[a-zA-Z ]+\]", "", markup).strip()
        self.send("error", message=clean)

    def confirm(self, prompt: str) -> bool:
        tool, args, risk = self._parse_confirmation(prompt)
        tool_call_id = f"call_{uuid.uuid4().hex}"
        self._active_tool_call_id = tool_call_id
        self.send(
            "tool_call",
            tool=tool,
            args=args,
            id=tool_call_id,
            risk=risk,
        )
        self._start_tool_task(tool, args)
        self.send("status", state="confirming")
        with self._approval_condition:
            while tool_call_id not in self._approvals and not self._shutdown:
                self._approval_condition.wait()
            return self._approvals.pop(tool_call_id, False)

    def tool_start(self, name: str, args: dict[str, Any]) -> None:
        if self._active_tool_call_id is None:
            self._active_tool_call_id = f"call_{uuid.uuid4().hex}"
            self.send(
                "tool_call",
                tool=name,
                args=args,
                id=self._active_tool_call_id,
                risk="safe",
            )
            self._start_tool_task(name, args)
        if name in {"read_file", "write_file"}:
            path = args.get("path")
            if isinstance(path, str):
                self.send("file_header", path=path)
                if name == "write_file":
                    self._files_edited += 1
        self.send("status", state="tool_waiting")

    def tool_result(self, name: str, shown: str) -> None:
        tool_call_id = self._active_tool_call_id or f"call_{uuid.uuid4().hex}"
        self.send(
            "tool_result",
            tool_call_id=tool_call_id,
            result=shown,
            exit_code=0 if not shown.startswith("[error]") else 1,
        )
        self._complete_active_task()
        self._active_tool_call_id = None

    def blocked(self, name: str, reason: str) -> None:
        self.send("error", message=f"{name} blocked: {reason}")

    def declined(self, name: str, reason: str) -> None:
        tool_call_id = self._active_tool_call_id or f"call_{uuid.uuid4().hex}"
        self.send(
            "tool_result",
            tool_call_id=tool_call_id,
            result=f"{name} declined: {reason}",
            exit_code=1,
        )
        self._complete_active_task()
        self._active_tool_call_id = None

    @staticmethod
    def _parse_confirmation(
        prompt: str,
    ) -> tuple[str, dict[str, Any], str]:
        tool_match = re.search(r"\[bold\](.*?)\[/bold\]", prompt)
        risk_match = re.search(r"\[yellow\](.*?)\[/yellow\]", prompt)
        args_match = re.search(r"\[/bold\]\s+(\{.*\})\s+—", prompt)
        tool = tool_match.group(1) if tool_match else "unknown"
        risk = risk_match.group(1).lower() if risk_match else "confirm"
        try:
            args = json.loads(args_match.group(1)) if args_match else {}
        except json.JSONDecodeError:
            args = {}
        return tool, args, risk


def main() -> int:
    return TuiBridge().run()


if __name__ == "__main__":
    raise SystemExit(main())
