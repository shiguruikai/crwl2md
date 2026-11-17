from __future__ import annotations

import re

import pytest

from web2md.site_builder import (
    FRONTMATTER_FIELDS,
    CrawledPageDoc,
    compute_relative_paths,
    format_frontmatter,
    generate_toc_files,
    normalize_url_key,
    parse_frontmatter_fields,
    rewrite_markdown_links,
)


def test_normalize_url_key():
    assert normalize_url_key("https://Example.COM/docs/sdk/#section") == "https://example.com/docs/sdk"
    assert normalize_url_key("https://example.com/docs/sdk/index.html") == "https://example.com/docs/sdk"


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


def test_rewrite_markdown_links_resolves_internal_external_images_and_code_blocks():
    url_to_relpath = {
        "https://docs.example.com/docs/sdk/getting-started": "sdk/getting-started.md",
        "https://docs.example.com/docs/cli/intro": "cli/intro.md",
    }
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
        url_to_relpath=url_to_relpath,
    )

    assert "[CLI Intro](../cli/intro.md#flags)" in rewritten
    assert "[Same](#install)" in rewritten
    assert "[Unlisted](https://docs.example.com/blog/release)" in rewritten
    assert "[External](https://github.com/org/repo)" in rewritten
    assert "![Diagram](https://docs.example.com/img/arch.png)" in rewritten
    assert '<img src="https://docs.example.com/img/html-arch.png" alt="HTML Diagram">' in rewritten
    assert "Do not rewrite [CLI](/docs/cli/intro) inside code fences." in rewritten


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


def test_format_frontmatter_escapes_special_characters_and_includes_utc_timestamp():
    fm = format_frontmatter('Guide: "Quotes"', "Line: one", "https://example.com/guide")

    assert fm.startswith("---\n")
    assert 'title: "Guide: \\"Quotes\\""' in fm
    assert 'description: "Line: one"' in fm
    assert "source: https://example.com/guide" in fm
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
            "source: https://example.com/intro",
            "---",
        ]
    )


def test_parse_frontmatter_fields_rejects_invalid_or_empty():
    assert parse_frontmatter_fields(None) == list(FRONTMATTER_FIELDS)
    with pytest.raises(ValueError, match="Unsupported frontmatter field"):
        parse_frontmatter_fields("title,unknown")
    with pytest.raises(ValueError, match="At least one frontmatter field"):
        parse_frontmatter_fields(" , ")
