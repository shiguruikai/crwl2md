from __future__ import annotations

import re

import pytest

from crwl2md.site_builder import (
    FRONTMATTER_FIELDS,
    CrawledPageDoc,
    build_link_lookup,
    compute_relative_paths,
    format_frontmatter,
    generate_toc_files,
    normalize_url_key,
    parse_frontmatter_fields,
    rewrite_markdown_links,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://Example.COM/docs/sdk/#section", "https://example.com/docs/sdk"),
        ("https://example.com/docs/sdk/index.html", "https://example.com/docs/sdk"),
        ("https://example.com/index.html", "https://example.com/"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com/docs//sdk/?page=2", "https://example.com/docs/sdk?page=2"),
        ("https://example.com/docs/x/../sdk/./api", "https://example.com/docs/sdk/api"),
        ("https://example.com/docs/../../../etc", "https://example.com/etc"),
        ("https://example.com:443/docs/a", "https://example.com/docs/a"),
        ("http://example.com:80/docs/a", "http://example.com/docs/a"),
        ("http://example.com:8080/docs/a", "http://example.com:8080/docs/a"),
        ("https://example.com/docs/a?utm_source=x&fbclid=123", "https://example.com/docs/a"),
        ("https://example.com/docs/a?b=2&utm_medium=email&a=1", "https://example.com/docs/a?a=1&b=2"),
    ],
)
def test_normalize_url_key(url: str, expected: str):
    key = normalize_url_key(url)

    assert key == expected


def test_compute_relative_paths_strips_common_prefix_and_avoids_index_collision():
    seed_url = "https://docs.example.com/docs/"
    urls = [
        "https://docs.example.com/docs/",
        "https://docs.example.com/docs/sdk/",
        "https://docs.example.com/docs/sdk/getting-started/",
        "https://docs.example.com/docs/cli/intro.html",
        "https://docs.example.com/docs/cli/index",
    ]

    mapping = compute_relative_paths(urls, seed_url)

    assert mapping["https://docs.example.com/docs/"] == "overview.md"
    assert mapping["https://docs.example.com/docs/sdk/"] == "sdk/overview.md"
    assert mapping["https://docs.example.com/docs/sdk/getting-started/"] == "sdk/getting-started.md"
    assert mapping["https://docs.example.com/docs/cli/intro.html"] == "cli/intro.md"
    assert mapping["https://docs.example.com/docs/cli/index"] == "cli/overview.md"


def test_compute_relative_paths_namespaces_multiple_hosts():
    urls = [
        "https://docs.example.com/sdk/start",
        "https://api.example.com/v1/auth",
    ]

    mapping = compute_relative_paths(urls, urls[0])

    assert mapping["https://docs.example.com/sdk/start"] == "docs.example.com/sdk/start.md"
    assert mapping["https://api.example.com/v1/auth"] == "api.example.com/v1/auth.md"


def test_compute_relative_paths_never_leaves_the_output_root():
    urls = [
        "https://example.com/docs/a",
        "https://example.com/docs/x/../../../../evil",
        "https://example.com/docs/../secret/..",
    ]

    mapping = compute_relative_paths(urls, urls[0])

    assert all(".." not in relpath.split("/") for relpath in mapping.values())
    assert mapping["https://example.com/docs/x/../../../../evil"] == "evil.md"


def test_compute_relative_paths_drops_trailing_dots_that_windows_would_strip():
    urls = ["https://example.com/docs/v1./intro", "https://example.com/docs/v2/notes."]

    mapping = compute_relative_paths(urls, "https://example.com/docs/")

    assert mapping == {
        "https://example.com/docs/v1./intro": "v1/intro.md",
        "https://example.com/docs/v2/notes.": "v2/notes.md",
    }


def test_compute_relative_paths_separates_paths_that_differ_only_by_case():
    urls = ["https://example.com/docs/API", "https://example.com/docs/api"]

    mapping = compute_relative_paths(urls, "https://example.com/docs/")

    assert mapping == {"https://example.com/docs/API": "API.md", "https://example.com/docs/api": "api-2.md"}


def test_compute_relative_paths_decodes_percent_encoded_segments():
    urls = [
        "https://example.com/docs/%E3%81%AF%E3%81%98%E3%82%81%E3%81%AB",
        "https://example.com/docs/release%20notes/v1%2F2",
        "https://example.com/docs/%2e%2e/%2e%2e/escape",
    ]

    mapping = compute_relative_paths(urls, "https://example.com/docs/")

    assert mapping == {
        "https://example.com/docs/%E3%81%AF%E3%81%98%E3%82%81%E3%81%AB": "はじめに.md",
        "https://example.com/docs/release%20notes/v1%2F2": "release notes/v1_2.md",
        "https://example.com/docs/%2e%2e/%2e%2e/escape": "page/page/escape.md",
    }


def test_compute_relative_paths_separates_pages_that_differ_only_by_query():
    urls = ["https://example.com/docs/list?page=1", "https://example.com/docs/list?page=2"]

    mapping = compute_relative_paths(urls, "https://example.com/docs/")

    relpaths = list(mapping.values())
    assert len(set(relpaths)) == 2
    assert all(re.fullmatch(r"list-[0-9a-f]{6}\.md", relpath) for relpath in relpaths)


def test_rewrite_markdown_links_resolves_internal_external_images_and_code_blocks():
    link_lookup = build_link_lookup(
        {
            "https://docs.example.com/docs/sdk/getting-started": "sdk/getting-started.md",
            "https://docs.example.com/docs/cli/intro": "cli/intro.md",
        }
    )
    markdown = "\n".join(
        [
            "See [CLI Intro](/docs/cli/intro#flags) and [Same](#install).",
            "Also check [Unlisted](/blog/release) and [External](https://github.com/org/repo).",
            "![Diagram](/img/arch.png)",
            '<img src="/img/html-arch.png" alt="HTML Diagram">',
            "",
            "```markdown",
            "Do not rewrite [CLI](/docs/cli/intro) inside code fences.",
            "```",
        ]
    )

    rewritten = rewrite_markdown_links(
        markdown,
        source_url="https://docs.example.com/docs/sdk/getting-started",
        source_relpath="sdk/getting-started.md",
        link_lookup=link_lookup,
    )

    assert "[CLI Intro](../cli/intro.md#flags)" in rewritten
    assert "[Same](#install)" in rewritten
    assert "[Unlisted](https://docs.example.com/blog/release)" in rewritten
    assert "[External](https://github.com/org/repo)" in rewritten
    assert "![Diagram](https://docs.example.com/img/arch.png)" in rewritten
    assert '<img src="https://docs.example.com/img/html-arch.png" alt="HTML Diagram">' in rewritten
    assert "Do not rewrite [CLI](/docs/cli/intro) inside code fences." in rewritten


def test_rewrite_markdown_links_leaves_inline_code_untouched():
    link_lookup = build_link_lookup({"https://docs.example.com/docs/intro": "intro.md"})
    markdown = "Write `[Intro](/docs/intro)` to link to [`intro`](/docs/intro)."

    rewritten = rewrite_markdown_links(markdown, "https://docs.example.com/docs/guide", "guide.md", link_lookup)

    assert rewritten == "Write `[Intro](/docs/intro)` to link to [`intro`](intro.md)."


def test_rewrite_markdown_links_matches_pages_regardless_of_html_extension():
    link_lookup = build_link_lookup(
        {
            "https://docs.example.com/docs/intro": "intro.md",
            "https://docs.example.com/docs/api.html": "api.md",
        }
    )
    markdown = "[Intro](/docs/intro.html) and [API](/docs/api)"

    rewritten = rewrite_markdown_links(markdown, "https://docs.example.com/docs/guide", "guide.md", link_lookup)

    assert rewritten == "[Intro](intro.md) and [API](api.md)"


def test_rewrite_markdown_links_encodes_characters_that_would_break_the_link():
    link_lookup = build_link_lookup(
        {
            "https://example.com/docs/%E3%81%AF%E3%81%98%E3%82%81%E3%81%AB": "はじめに.md",
            "https://example.com/docs/release%20notes/C%23%20(new)": "release notes/C# (new).md",
        }
    )
    markdown = "[Intro](/docs/%E3%81%AF%E3%81%98%E3%82%81%E3%81%AB) and [Notes](/docs/release%20notes/C%23%20(new)#top)"

    rewritten = rewrite_markdown_links(markdown, "https://example.com/docs/guide", "guide.md", link_lookup)

    assert rewritten == "[Intro](はじめに.md) and [Notes](release%20notes/C%23%20%28new%29.md#top)"


def test_rewrite_markdown_links_handles_parentheses_in_link_destinations():
    link_lookup = build_link_lookup({"https://example.org/wiki/Python_(language)": "Python_(language).md"})
    markdown = "See [Python](/wiki/Python_(language)) and [Ruby](/wiki/Ruby_(language))."

    rewritten = rewrite_markdown_links(markdown, "https://example.org/wiki/Main", "Main.md", link_lookup)

    assert rewritten == "See [Python](Python_%28language%29.md) and [Ruby](https://example.org/wiki/Ruby_(language))."


def test_rewrite_markdown_links_preserves_double_and_single_quoted_titles():
    link_lookup = build_link_lookup({"https://docs.example.com/docs/b": "b.md"})
    markdown = """[B1](/docs/b "Double") and [B2](/docs/b 'Single')"""

    rewritten = rewrite_markdown_links(markdown, "https://docs.example.com/docs/a", "a.md", link_lookup)

    assert rewritten == """[B1](b.md "Double") and [B2](b.md 'Single')"""


def test_rewrite_markdown_links_absolutizes_relative_links_without_lookup():
    markdown = "[Next](../next) and [Top](/)"

    rewritten = rewrite_markdown_links(markdown, "https://docs.example.com/docs/sdk/page", "", {})

    assert rewritten == "[Next](https://docs.example.com/docs/next) and [Top](https://docs.example.com/)"


def test_generate_toc_files_respects_nav_order_and_subdirectories():
    pages = [
        CrawledPageDoc(
            url="https://docs.example.com/docs/sdk/actions",
            relpath="sdk/actions.md",
            title="Actions",
            description="Action concepts.",
            markdown="# Actions\n",
        ),
        CrawledPageDoc(
            url="https://docs.example.com/docs/sdk/getting-started",
            relpath="sdk/getting-started.md",
            title="Getting Started",
            description="Setup guide.",
            markdown="# Getting Started\n",
        ),
        CrawledPageDoc(
            url="https://docs.example.com/docs/intro",
            relpath="intro.md",
            title="Introduction",
            description="Welcome to the docs.",
            markdown="# Introduction\n",
        ),
    ]
    nav_order = [
        "https://docs.example.com/docs/sdk/getting-started",
        "https://docs.example.com/docs/sdk/actions",
    ]

    tocs = generate_toc_files(pages, nav_order=nav_order, root_title="Example Docs")

    assert set(tocs.keys()) == {"index.md", "sdk/index.md"}
    root_toc = tocs["index.md"]
    assert "# Example Docs" in root_toc
    assert "## Subcategories" in root_toc
    assert "- [Sdk](sdk/index.md)" in root_toc
    assert "## Documents" in root_toc
    assert "- [Introduction](intro.md) - Welcome to the docs." in root_toc

    sdk_toc = tocs["sdk/index.md"]
    assert sdk_toc.index("Getting Started") < sdk_toc.index("Actions")


def test_generate_toc_files_escapes_brackets_in_link_labels():
    pages = [
        CrawledPageDoc(
            url="https://docs.example.com/docs/list",
            relpath="list.md",
            title="[Deprecated] List[T]",
            description="Old API.",
            markdown="# List\n",
        ),
    ]

    tocs = generate_toc_files(pages)

    assert r"- [\[Deprecated\] List\[T\]](list.md) - Old API." in tocs["index.md"]


def test_generate_toc_files_encodes_spaces_in_link_targets():
    pages = [
        CrawledPageDoc(
            url="https://docs.example.com/docs/release%20notes/v1",
            relpath="release notes/first release.md",
            title="First release",
            description="Notes.",
            markdown="# First release\n",
        ),
    ]

    tocs = generate_toc_files(pages)

    assert "- [Release notes](release%20notes/index.md)" in tocs["index.md"]
    assert "- [First release](first%20release.md) - Notes." in tocs["release notes/index.md"]


def test_format_frontmatter_escapes_special_characters_and_includes_utc_timestamp():
    fm = format_frontmatter('Guide: "Quotes"', "Line: one", "https://example.com/guide?a=1: b #c")

    assert fm.startswith("---\n")
    assert 'title: "Guide: \\"Quotes\\""' in fm
    assert 'description: "Line: one"' in fm
    assert 'source: "https://example.com/guide?a=1: b #c"' in fm
    assert re.search(r"^timestamp: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", fm, re.MULTILINE)


def test_format_frontmatter_selects_requested_fields_in_order():
    fields = parse_frontmatter_fields("timestamp, title, source")

    fm = format_frontmatter(
        "Intro",
        "Desc",
        "https://example.com/intro",
        timestamp="2026-11-18T00:00:00Z",
        fields=fields,
    )

    assert fm == "\n".join(
        [
            "---",
            "timestamp: 2026-11-18T00:00:00Z",
            'title: "Intro"',
            'source: "https://example.com/intro"',
            "---",
        ]
    )


def test_format_frontmatter_returns_empty_string_when_no_field_has_a_value():
    fm = format_frontmatter("Intro", "Desc", source_url="", fields=["source"])

    assert fm == ""


def test_parse_frontmatter_fields_defaults_to_all_fields():
    fields = parse_frontmatter_fields(None)

    assert fields == list(FRONTMATTER_FIELDS)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("title,unknown", "Unsupported frontmatter field"),
        (" , ", "At least one frontmatter field"),
    ],
)
def test_parse_frontmatter_fields_rejects_invalid_or_empty(raw: str, message: str):
    with pytest.raises(ValueError, match=message):
        parse_frontmatter_fields(raw)
