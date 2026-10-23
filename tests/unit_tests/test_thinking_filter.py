"""Unit tests for the <thinking> stream filter."""

from backend.ia.thinking_filter import ThinkingStripper, strip_thinking


def _stream(chunks: list[str]) -> str:
    stripper = ThinkingStripper()
    return "".join(stripper.feed(c) for c in chunks) + stripper.flush()


def test_plain_text_is_untouched():
    assert strip_thinking("Hola, ¿qué tal?") == "Hola, ¿qué tal?"


def test_complete_block_in_one_chunk():
    assert strip_thinking("<thinking>razono</thinking>\n\nRespuesta") == "Respuesta"


def test_tags_split_across_chunks():
    chunks = ["<thin", "king>razo", "no</thin", "king>\n\nHola", " mundo"]
    assert _stream(chunks) == "Hola mundo"


def test_block_in_the_middle_keeps_surrounding_text():
    assert strip_thinking("Antes <thinking>x</thinking>después") == "Antes después"


def test_several_blocks():
    text = "<thinking>a</thinking>Uno<thinking>b</thinking> dos"
    assert strip_thinking(text) == "Uno dos"


def test_unclosed_block_is_dropped():
    assert strip_thinking("Hola <thinking>sin cerrar") == "Hola "


def test_nothing_shown_while_inside_block():
    stripper = ThinkingStripper()
    assert stripper.feed("<thinking>pensando") == ""
    assert stripper.feed(" más") == ""


def test_false_alarm_prefix_is_released_on_flush():
    assert _stream(["a < b ", "<thi"]) == "a < b <thi"


def test_single_characters():
    text = "<thinking>x</thinking>Hola"
    assert _stream(list(text)) == "Hola"
