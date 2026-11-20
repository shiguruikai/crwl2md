from __future__ import annotations

import re
from collections.abc import Callable, Iterator

# A fence may be indented (list items) or quoted (admonitions rendered as blockquotes).
_QUOTE_PREFIX_RE = re.compile(r"^[ \t>]*")
_FENCE_RE = re.compile(r"^([ \t>]*)(`{3,}|~{3,})")
_BACKTICK_RUN_RE = re.compile(r"`+")


def iter_lines_with_code_flag(markdown: str) -> Iterator[tuple[str, bool]]:
    """Yield each line with a flag telling whether it belongs to a fenced code block (fence lines included)."""
    open_fence: str | None = None
    open_quote_depth = 0
    for line in markdown.split("\n"):
        quote_prefix = _QUOTE_PREFIX_RE.match(line)
        quote_depth = quote_prefix.group(0).count(">") if quote_prefix is not None else 0

        # CommonMark closes a fenced code block inside a blockquote as soon as the quote prefix ends.
        if open_fence is not None and quote_depth < open_quote_depth:
            open_fence = None
            open_quote_depth = 0

        match = _FENCE_RE.match(line)
        if open_fence is None:
            is_opening = False
            if match:
                fence = match.group(2)
                info_string = line[match.end() :]
                # CommonMark: backtick fence info strings cannot contain backticks (prevents inline code spans).
                if fence[0] != "`" or "`" not in info_string:
                    open_fence = fence
                    open_quote_depth = quote_depth
                    is_opening = True
            yield line, is_opening
            continue

        yield line, True
        if match and quote_depth == open_quote_depth:
            fence = match.group(2)
            has_info_string = bool(line[match.end() :].strip())
            # A closing fence uses the same character, is at least as long, and carries no info string.
            if fence[0] == open_fence[0] and len(fence) >= len(open_fence) and not has_info_string:
                open_fence = None
                open_quote_depth = 0


def _code_span_ranges(line: str) -> list[tuple[int, int]]:
    # CommonMark: a code span opens with a backtick run and closes at the next run of exactly the same length.
    runs = [match.span() for match in _BACKTICK_RUN_RE.finditer(line)]
    closer_of: dict[int, int] = {}
    next_run_of_length: dict[int, int] = {}
    for index in range(len(runs) - 1, -1, -1):
        length = runs[index][1] - runs[index][0]
        if length in next_run_of_length:
            closer_of[index] = next_run_of_length[length]
        next_run_of_length[length] = index

    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(runs):
        closer = closer_of.get(index)
        if closer is None:
            index += 1
        else:
            ranges.append((runs[index][0], runs[closer][1]))
            index = closer + 1
    return ranges


def sub_outside_code_spans(pattern: re.Pattern[str], repl: Callable[[re.Match[str]], str], line: str) -> str:
    """Apply `pattern.sub` to a prose line while leaving matches that start inside an inline code span untouched."""
    code_spans = _code_span_ranges(line) if "`" in line else []

    def guarded(match: re.Match[str]) -> str:
        if any(start <= match.start() < end for start, end in code_spans):
            return match.group(0)
        return repl(match)

    return pattern.sub(guarded, line)
