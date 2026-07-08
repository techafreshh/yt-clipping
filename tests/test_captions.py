"""Tests for the captions module."""

from pathlib import Path

import pytest

from shorts.captions import WORKING_DIR, _format_ass_time, _group_words, _extract_words, generate_ass
from shorts.transcript import Transcript, TranscriptSegment


def test_format_ass_time_zero():
    assert _format_ass_time(0.0) == "0:00:00.00"


def test_format_ass_time_minutes():
    assert _format_ass_time(65.5) == "0:01:05.50"


def test_format_ass_time_hours():
    assert _format_ass_time(3661.50) == "1:01:01.50"


def test_format_ass_time_negative():
    assert _format_ass_time(-5.0) == "0:00:00.00"


def test_extract_words_filters_window():
    transcript = Transcript(
        segments=[],
        words=[
            TranscriptSegment(start=5.0, end=6.0, text="before"),
            TranscriptSegment(start=10.0, end=11.0, text="inside"),
            TranscriptSegment(start=25.0, end=26.0, text="after"),
        ],
    )
    words = _extract_words(transcript, 10.0, 20.0)
    assert len(words) == 1
    assert words[0].text == "inside"
    assert words[0].start == 0.0


def test_group_words_basic():
    from shorts.captions import CaptionWord

    words = [
        CaptionWord("hello", 0.0, 0.5),
        CaptionWord("world", 0.6, 1.0),
        CaptionWord("how", 1.1, 1.5),
        CaptionWord("are", 1.6, 2.0),
    ]
    groups = _group_words(words, max_group=4)
    assert len(groups) == 1
    assert len(groups[0]) == 4


def test_group_words_breaks_on_pause():
    from shorts.captions import CaptionWord

    words = [
        CaptionWord("hello", 0.0, 0.5),
        CaptionWord("world", 0.6, 1.0),
        CaptionWord("gap", 2.0, 2.5),
        CaptionWord("here", 2.6, 3.0),
    ]
    groups = _group_words(words, max_group=4, pause_threshold=0.4)
    assert len(groups) == 2


def test_group_words_breaks_on_max():
    from shorts.captions import CaptionWord

    words = [
        CaptionWord("a", 0.0, 0.3),
        CaptionWord("b", 0.3, 0.6),
        CaptionWord("c", 0.6, 0.9),
        CaptionWord("d", 0.9, 1.2),
        CaptionWord("e", 1.2, 1.5),
    ]
    groups = _group_words(words, max_group=3)
    assert len(groups) == 2
    assert len(groups[0]) == 3
    assert len(groups[1]) == 2


def test_generate_ass_word_level(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.captions.WORKING_DIR", tmp_path)
    transcript = Transcript(
        segments=[TranscriptSegment(start=10.0, end=15.0, text="hello world")],
        words=[
            TranscriptSegment(start=10.0, end=11.0, text="hello"),
            TranscriptSegment(start=11.0, end=12.0, text="world"),
        ],
    )
    result = generate_ass("ep1", "test-clip", transcript, 10.0, 15.0)
    assert result == tmp_path / "ep1" / "test-clip.ass"
    assert result.exists()
    content = result.read_text()
    assert "[Script Info]" in content
    assert "[V4+ Styles]" in content
    assert "[Events]" in content
    assert "HELLO" in content
    assert "WORLD" in content
    assert "\\c&H00FFFF&" in content


def test_generate_ass_highlighting(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.captions.WORKING_DIR", tmp_path)
    transcript = Transcript(
        segments=[],
        words=[
            TranscriptSegment(start=0.0, end=0.5, text="one"),
            TranscriptSegment(start=0.6, end=1.0, text="two"),
            TranscriptSegment(start=1.1, end=1.5, text="three"),
        ],
    )
    result = generate_ass("ep1", "highlight", transcript, 0.0, 2.0)
    content = result.read_text()
    assert content.count("\\c&H00FFFF&") == 3


def test_generate_ass_segment_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.captions.WORKING_DIR", tmp_path)
    transcript = Transcript(
        segments=[TranscriptSegment(start=5.0, end=10.0, text="segment text")],
        words=None,
    )
    result = generate_ass("ep1", "seg-clip", transcript, 5.0, 10.0)
    content = result.read_text()
    assert "SEGMENT" in content
    assert "TEXT" in content
    assert "Dialogue:" in content


def test_generate_ass_filters_outside_window(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.captions.WORKING_DIR", tmp_path)
    transcript = Transcript(
        segments=[],
        words=[
            TranscriptSegment(start=5.0, end=6.0, text="before"),
            TranscriptSegment(start=10.0, end=11.0, text="inside"),
            TranscriptSegment(start=25.0, end=26.0, text="after"),
        ],
    )
    result = generate_ass("ep1", "filter-clip", transcript, 10.0, 20.0)
    content = result.read_text()
    assert "INSIDE" in content
    assert "BEFORE" not in content
    assert "AFTER" not in content


def test_generate_ass_uppercase(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.captions.WORKING_DIR", tmp_path)
    transcript = Transcript(
        segments=[TranscriptSegment(start=0.0, end=2.0, text="Hello World")],
    )
    result = generate_ass("ep1", "upper", transcript, 0.0, 2.0)
    content = result.read_text()
    assert "HELLO" in content
    assert "WORLD" in content
    assert "Hello" not in content
    assert "World" not in content


def test_generate_ass_style(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.captions.WORKING_DIR", tmp_path)
    transcript = Transcript(
        segments=[TranscriptSegment(start=0.0, end=5.0, text="hi")],
    )
    result = generate_ass("ep1", "style-clip", transcript, 0.0, 5.0)
    content = result.read_text()
    assert "&H00FFFFFF" in content
    assert "&H00000000" in content
    assert "Arial Black" in content
    assert "WrapStyle: 0" in content


def test_generate_ass_with_title(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.captions.WORKING_DIR", tmp_path)
    result = generate_ass("ep1", "title-clip", None, 0.0, 5.0, title="My Awesome Title", title_color="purple")
    assert result.exists()
    content = result.read_text()
    assert "Style: Title,Arial,48,&H00FFFFFF,&H00000000,&H00CE5B4A,&H00CE5B4A" in content
    assert "Dialogue: 0,0:00:00.00,9:59:59.99,Title,,0,0,0,,My Awesome Title" in content


def test_generate_ass_with_custom_title_color(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.captions.WORKING_DIR", tmp_path)
    result = generate_ass("ep1", "title-clip-red", None, 0.0, 5.0, title="My Awesome Title", title_color="red")
    content = result.read_text()
    assert "Style: Title,Arial,48,&H00FFFFFF,&H00000000,&H00481DE1,&H00481DE1" in content


def test_generate_ass_title_wrapping(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.captions.WORKING_DIR", tmp_path)
    title = "POV: The highest paid engineer at your company gets fired"
    result = generate_ass("ep1", "title-wrap", None, 0.0, 5.0, title=title, title_color="purple")
    content = result.read_text()
    # Check that it splits into multiple Dialogue events
    assert "Dialogue: 0,0:00:00.00,9:59:59.99,Title,,0,0,0,,POV: The highest paid" in content
    assert "Dialogue: 0,0:00:00.00,9:59:59.99,Title,,0,0,0,,engineer at your company" in content
    assert "Dialogue: 0,0:00:00.00,9:59:59.99,Title,,0,0,0,,gets fired" in content

