"""Strip ``<thinking>...</thinking>`` blocks from streamed LLM output.

Some models (e.g. Amazon Nova) write their reasoning as plain text wrapped in
``<thinking>`` tags when they use tools. The text arrives in small chunks, so
a tag can be split across chunks (``<thin`` + ``king>``). ``ThinkingStripper``
keeps a tiny buffer to handle that case.
"""

OPEN_TAG = "<thinking>"
CLOSE_TAG = "</thinking>"


def _partial_suffix_len(text: str, tag: str) -> int:
    """Return the length of the longest suffix of ``text`` that is a proper prefix of ``tag``."""
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if text.endswith(tag[:size]):
            return size
    return 0


class ThinkingStripper:
    """Stateful filter: feed chunks in order, get back only the visible text."""

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False
        # Drop blank space until the first visible text, so a leading block does
        # not leave empty lines at the top. Once text was shown, spacing is kept.
        self._lstrip_next = True

    def _emit(self, segment: str, out: list[str]) -> None:
        if self._lstrip_next:
            segment = segment.lstrip()
        if segment:
            self._lstrip_next = False
            out.append(segment)

    def feed(self, chunk: str) -> str:
        """Process one chunk and return the text that is safe to show."""
        self._buffer += chunk
        out: list[str] = []
        while True:
            if not self._inside:
                start = self._buffer.find(OPEN_TAG)
                if start >= 0:
                    self._emit(self._buffer[:start], out)
                    self._buffer = self._buffer[start + len(OPEN_TAG) :]
                    self._inside = True
                    continue
                keep = _partial_suffix_len(self._buffer, OPEN_TAG)
                cut = len(self._buffer) - keep
                self._emit(self._buffer[:cut], out)
                self._buffer = self._buffer[cut:]
                break
            end = self._buffer.find(CLOSE_TAG)
            if end >= 0:
                self._buffer = self._buffer[end + len(CLOSE_TAG) :]
                self._inside = False
                continue
            keep = _partial_suffix_len(self._buffer, CLOSE_TAG)
            self._buffer = self._buffer[len(self._buffer) - keep :]
            break
        return "".join(out)

    def flush(self) -> str:
        """Call once at the end of the stream; unclosed blocks are dropped."""
        out: list[str] = []
        if not self._inside:
            self._emit(self._buffer, out)
        self._buffer = ""
        self._inside = False
        return "".join(out)


def strip_thinking(text: str) -> str:
    """One-shot version for non-streaming responses."""
    stripper = ThinkingStripper()
    return stripper.feed(text) + stripper.flush()
