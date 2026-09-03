"""Tester for LLM-baserad context compression."""
from hund.agent.context import compress_llm, maybe_compress, CompressionResult
from hund.providers.base import Message, CompletionResult

class _FakeClient:
    """Mockad provider-client for tester."""
    def __init__(self, response_text="[SUMMERAD konversation]"):
        self.response_text = response_text
        self.calls = []

    def complete(self, messages, tools=None, model=None, **kwargs):
        self.calls.append(messages)
        return CompletionResult(text=self.response_text)

    def stream(self, *args, **kwargs):
        raise NotImplementedError


def test_compress_llm_returns_none_for_short_conversation():
    """For fa meddelanden -> None (ingen komprimering behovs)."""
    client = _FakeClient()
    msgs = [Message(role="system", content="system"), Message(role="user", content="hej")]
    result = compress_llm(client, msgs)
    assert result is None


def test_compress_llm_summarizes():
    """LLM-summary injectas som separat meddelande, systemprompt oforandrad."""
    client = _FakeClient("[SUMMERAD] Viktiga punkter...")
    msgs = [
        Message(role="system", content="HUND SYSTEM"),
        Message(role="user", content="msg1"),
        Message(role="assistant", content="reply1"),
        Message(role="user", content="msg2"),
        Message(role="assistant", content="reply2"),
        Message(role="user", content="msg3"),
        Message(role="assistant", content="reply3"),
    ]
    result = compress_llm(client, msgs, keep_recent=2)
    assert result is not None
    assert result.compressed
    assert result.messages[0].content == "HUND SYSTEM"  # oforandrad
    assert "SUMMERAD" in result.messages[1].content     # markor + summary


def test_compress_llm_fallback_on_error():
    """Provider-fel -> None (ring fallback)."""
    client = _FakeClient()
    client.complete = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("fail"))
    msgs = [Message(role="system", content="s")] + [Message(role="user", content=str(i)) for i in range(20)]
    result = compress_llm(client, msgs, keep_recent=2)
    assert result is None


def test_maybe_compress_uses_llm_first():
    """maybe_compress med client -> provar LLM forst."""
    client = _FakeClient("[SUMMERAD]")
    msgs = [Message(role="system", content="s")]
    # Manga meddelanden for att trigga komprimering
    for i in range(50):
        msgs.append(Message(role="user", content="x" * 200))
    result = maybe_compress(msgs, max_tokens=10, keep_recent=2, client=client)
    assert result.compressed
    assert len(client.calls) == 1  # LLM anropades


def test_tcb_not_in_compress_target():
    """TCB-text i systemprompten ska INTE skickas till LLM:en for summering."""
    client = _FakeClient()
    msgs = [
        Message(role="system", content="TCB REGEL: faar aldrig andras"),
        Message(role="user", content="msg1"),
        Message(role="assistant", content="reply1"),
        Message(role="user", content="msg2"),
        Message(role="assistant", content="reply2"),
        Message(role="user", content="msg3"),
        Message(role="assistant", content="reply3"),
    ]
    result = compress_llm(client, msgs, keep_recent=2)
    assert result is not None
    # Systemprompten skickas INTE till LLM
    sent_text = client.calls[0][1].content  # user-meddelandet till LLM
    assert "TCB REGEL" not in sent_text


def test_maybe_compress_with_client_preserves_system_and_invokes_llm():
    """Verify that maybe_compress with client uses LLM and returns method='llm'."""
    client = _FakeClient("[SUMMERAD] Kärnpunkter bevarade.")
    msgs = [Message(role="system", content="SYS PROMPT")]
    for i in range(40):
        msgs.append(Message(role="user", content=f"long prompt turn {i} " * 20))
        msgs.append(Message(role="assistant", content=f"long answer turn {i} " * 20))

    res = maybe_compress(msgs, max_tokens=100, keep_recent=4, client=client)
    assert res.compressed is True
    assert res.method == "llm"
    assert res.messages[0].content == "SYS PROMPT"
    assert "[KOMPRIMERAD via LLM" in res.messages[1].content
    assert len(client.calls) == 1


def test_compress_llm_preserves_primary_user_task():
    """compress_llm must preserve messages[1] (primary user goal) structurally."""
    client = _FakeClient("[SUMMERAD] Kärnpunkter bevarade.")
    msgs = [
        Message(role="system", content="SYS PROMPT"),
        Message(role="user", content="BYGG EN SUPER-AGENT I PYTHON"),
    ]
    for i in range(10):
        msgs.append(Message(role="assistant", content=f"assistant turn {i} " * 5))
        msgs.append(Message(role="user", content=f"user turn {i} " * 5))

    res = compress_llm(client, msgs, keep_recent=2)
    assert res is not None
    assert res.compressed is True
    # System prompt at index 0
    assert res.messages[0].content == "SYS PROMPT"
    # Marker at index 1
    assert "[KOMPRIMERAD via LLM" in res.messages[1].content
    # Primary task preserved at index 2
    assert res.messages[2].role == "user"
    assert res.messages[2].content == "BYGG EN SUPER-AGENT I PYTHON"
    # Recent turns follow
    assert res.messages[-1].role == "user"
    assert "user turn 9" in res.messages[-1].content


def test_compress_and_compress_llm_preserve_task_state():
    """TaskState survives both compress() and compress_llm()."""
    from hund.agent.context import TaskState, compress

    state = TaskState(source="user_cli", goal="Implement Track 18", target_file="context.py")
    client = _FakeClient("[SUMMERAD] Kärnpunkter bevarade.")

    msgs = [
        Message(role="system", content="SYS PROMPT"),
        Message(role="user", content="PRIMARY TASK"),
    ]
    for i in range(10):
        msgs.append(Message(role="assistant", content=f"reply {i} " * 5))
        msgs.append(Message(role="user", content=f"next {i} " * 5))

    # Test deterministic compress with task_state
    det_res = compress(msgs, keep_recent=2, task_state=state)
    assert det_res.compressed is True
    state_msgs = [m for m in det_res.messages if "[TASK_STATE" in (m.content or "")]
    assert len(state_msgs) == 1
    assert "Implement Track 18" in state_msgs[0].content
    assert "målfil=context.py" in state_msgs[0].content

    # Test LLM compress with task_state
    llm_res = compress_llm(client, msgs, keep_recent=2, task_state=state)
    assert llm_res is not None
    assert llm_res.compressed is True
    llm_state_msgs = [m for m in llm_res.messages if "[TASK_STATE" in (m.content or "")]
    assert len(llm_state_msgs) == 1
    assert "Implement Track 18" in llm_state_msgs[0].content
    assert "målfil=context.py" in llm_state_msgs[0].content


def test_compression_threshold_derivation():
    """Verify compression_threshold derives ~80% of context_window, with fallback."""
    from hund.agent.context import DEFAULT_MAX_TOKENS, compression_threshold

    assert compression_threshold(131072) == 104857  # ~104k
    assert compression_threshold(65536) == 52428
    assert compression_threshold(None) == DEFAULT_MAX_TOKENS
    assert compression_threshold(0) == DEFAULT_MAX_TOKENS


