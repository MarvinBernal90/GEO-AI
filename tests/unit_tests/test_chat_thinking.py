"""The assistant stream must hide <thinking> blocks and save a clean history."""

from types import SimpleNamespace

from backend.ia import chat


class _FakeGraph:
    """Mimics ``graph.stream(..., stream_mode="messages")`` with plain text chunks."""

    def __init__(self, pieces):
        self._pieces = pieces

    def stream(self, *_args, **_kwargs):
        for piece in self._pieces:
            chunk = SimpleNamespace(content=piece, tool_calls=None, tool_call_chunks=None, additional_kwargs={})
            yield chunk, {"langgraph_node": "assistant"}


def _run(tmp_path, monkeypatch, pieces):
    monkeypatch.setattr(chat, "REPO_ROOT", tmp_path)
    (tmp_path / "chat_history").mkdir(exist_ok=True)
    return list(chat._request_stream("hola", "u:1", graph=_FakeGraph(pieces)))


def test_stream_hides_thinking_and_saves_clean_history(tmp_path, monkeypatch):
    events = _run(tmp_path, monkeypatch, ["<thin", "king>razono</thinking>\n\n", "Hola", " mundo"])

    shown = "".join(e["text"] for e in events if e["type"] == "token")
    assert shown == "Hola mundo"
    assert events[-1] == {"type": "done", "text": "Hola mundo"}
    assert "thinking" not in (tmp_path / "chat_history" / "u:1.txt").read_text()


def test_stream_keeps_normal_text_ending_with_a_lone_bracket(tmp_path, monkeypatch):
    events = _run(tmp_path, monkeypatch, ["Texto normal ", "y <b"])

    assert events[-1] == {"type": "done", "text": "Texto normal y <b"}
