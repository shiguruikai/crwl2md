from __future__ import annotations

import re

from web2md.markdown_code import iter_lines_with_code_flag, sub_outside_code_spans

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _mark(match: re.Match[str]) -> str:
    return "<LINK>"


def test_iter_lines_with_code_flag_marks_fence_lines_and_their_content():
    markdown = "intro\n```python\ncode\n```\noutro"

    flags = [in_code for _, in_code in iter_lines_with_code_flag(markdown)]

    assert flags == [False, True, True, True, False]


def test_iter_lines_with_code_flag_keeps_shorter_fence_inside_longer_fence():
    markdown = "````markdown\n```python\nprint(1)\n```\n````\nprose"

    flags = [in_code for _, in_code in iter_lines_with_code_flag(markdown)]

    assert flags == [True, True, True, True, True, False]


def test_iter_lines_with_code_flag_does_not_close_on_a_different_fence_character():
    markdown = "~~~\n```\n~~~\nprose"

    flags = [in_code for _, in_code in iter_lines_with_code_flag(markdown)]

    assert flags == [True, True, True, False]


def test_iter_lines_with_code_flag_detects_fences_inside_blockquotes_and_lists():
    markdown = "> ```bash\n> ls\n> ```\n  ```\n  indented\n  ```\nprose"

    flags = [in_code for _, in_code in iter_lines_with_code_flag(markdown)]

    assert flags == [True, True, True, True, True, True, False]


def test_sub_outside_code_spans_leaves_matches_inside_inline_code_untouched():
    line = "See [a](/a), `[b](/b)` and ``[c](/c) ` tick``."

    result = sub_outside_code_spans(_LINK_RE, _mark, line)

    assert result == "See <LINK>, `[b](/b)` and ``[c](/c) ` tick``."


def test_sub_outside_code_spans_rewrites_links_whose_label_contains_inline_code():
    line = "Call [`foo()`](/api/foo) first."

    result = sub_outside_code_spans(_LINK_RE, _mark, line)

    assert result == "Call <LINK> first."


def test_sub_outside_code_spans_treats_unclosed_backticks_as_plain_text():
    line = "A stray ` backtick before [a](/a)."

    result = sub_outside_code_spans(_LINK_RE, _mark, line)

    assert result == "A stray ` backtick before <LINK>."
