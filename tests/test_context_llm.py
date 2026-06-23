"""Tester for LLM-baserad context compression."""
from hund.agent.context import compress_llm, maybe_compress, CompressionResult
from hund.providers.base import Message, CompletionResult

class _FakeClient:
    """Mockad provider-client for tester."""
    def __init__(self, response_text="[SUMMERAD konversation]"):
        self.response_text = response_text
        self.calls = []

    def complete(self, messages, tools=None, model=None):
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
