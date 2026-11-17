from __future__ import annotations

import pytest

from web2md.extractors import (
    EXTRACTOR_METHODS,
    extract_markdown,
    extract_page_metadata,
    extract_sidebar_links,
)

SAMPLE_DOCUSAURUS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Getting Started | Example Docs</title>
  <meta name="description" content="Learn how to install and configure Example SDK in minutes." />
</head>
<body>
  <header role="banner">
    <nav><a href="/">Home</a><a href="/docs/">Docs</a></nav>
  </header>
  <div class="layout">
    <aside class="sidebar">
      <nav aria-label="Docs sidebar">
        <a href="/docs/intro">Introduction</a>
        <a href="/docs/sdk/getting-started">Getting Started</a>
        <a href="/docs/sdk/actions">Actions</a>
        <a href="https://external.example.org/blog">External Blog</a>
      </nav>
    </aside>
    <main>
      <nav aria-label="Breadcrumbs" class="breadcrumbs">
        <a href="/">Home</a> / <a href="/docs/sdk/">SDK</a> / Getting Started
      </nav>
      <article>
        <header>
          <h1>Getting Started<a class="hash-link" href="#getting-started">\u200b</a></h1>
        </header>
        <p>Install the CLI and run your first <strong>project</strong>.</p>
        <h2>Installation<a class="hash-link" href="#installation">\u200b</a></h2>
        <div class="language-bash">
          <pre><code class="language-bash">uv add web2md
uv run web2md --help</code></pre>
          <button type="button">Copy</button>
        </div>
        <table>
          <thead><tr><th>Option</th><th>Default</th></tr></thead>
          <tbody><tr><td><code>--method</code></td><td>dom-markdownify</td></tr></tbody>
        </table>
      </article>
      <div class="table-of-contents">
        <a href="#installation">Installation</a>
      </div>
      <a class="theme-edit-this-page" href="https://github.com/org/repo/edit/main/doc.md">Edit this page</a>
      <nav class="pagination-nav">
        <a href="/docs/intro">Previous Introduction</a>
        <a href="/docs/sdk/actions">Next Actions</a>
      </nav>
    </main>
  </div>
  <footer>Copyright 2026 Example</footer>
</body>
</html>
"""


def test_extract_markdown_dom_markdownify():
    html = SAMPLE_DOCUSAURUS_HTML

    md = extract_markdown(html, url="https://docs.example.com/docs/sdk/getting-started", method="dom-markdownify")

    assert "# Getting Started" in md
    assert "Install the CLI and run your first **project**." in md
    assert "```bash\nuv add web2md\nuv run web2md --help\n```" in md
    assert "| Option | Default |" in md
    assert "Breadcrumbs" not in md
    assert "Edit this page" not in md
    assert "Previous Introduction" not in md
    assert "External Blog" not in md
    assert "\u200b" not in md
    assert "Copyright 2026" not in md


def test_extract_markdown_crawl4ai_cleans_nav_and_preserves_body():
    raw_c4ai = "\n".join(
        [
            "* [Home](https://docs.example.com/)",
            "* SDK",
            "",
            "# Getting Started[\u200b](https://docs.example.com/#top)",
            "",
            "Body paragraph here.",
            "",
            "[Edit this page](https://github.com/org/repo/edit/main/doc.md)",
            "[Next Actions](https://docs.example.com/docs/sdk/actions)",
        ]
    )

    md = extract_markdown(SAMPLE_DOCUSAURUS_HTML, method="crawl4ai", crawl4ai_markdown=raw_c4ai)

    assert md.startswith("# Getting Started\n")
    assert "Body paragraph here." in md
    assert "Edit this page" not in md
    assert "Next Actions" not in md
    assert "\u200b" not in md


def test_extract_markdown_crawl4ai_preserves_content_without_h1():
    raw_c4ai = "Intro paragraph without top-level heading.\n\n## Section\n\nDetails."

    md = extract_markdown("<html><body><p>Intro</p></body></html>", method="crawl4ai", crawl4ai_markdown=raw_c4ai)

    assert "Intro paragraph without top-level heading." in md
    assert "## Section" in md


@pytest.mark.parametrize("method", EXTRACTOR_METHODS)
def test_extract_markdown_all_methods_extract_main_text(method):
    html = """
    <html><head><title>Guide | Docs</title></head>
    <body>
      <article>
        <h1>Guide</h1>
        <p>This guide explains how to crawl technical documentation and convert every article into clean Markdown files for offline reading.</p>
        <p>Each extracted section preserves headings, links, and code blocks accurately across multiple paragraphs of prose.</p>
      </article>
    </body></html>
    """

    md = extract_markdown(html, url="https://docs.example.com/guide", method=method)

    assert "clean Markdown files" in md


def test_extract_markdown_dom_markdownify_supports_nested_code_lang_admonition_and_multiline_links():
    html = """
    <html><body><main>
      <h1>Install</h1>
      <div class="container_prVO language-bash">
        <div class="title_SCW8">Terminal</div>
        <div class="codeContainer_vNK6">
          <pre><code>npm install -g @elgato/cli</code></pre>
        </div>
      </div>
      <div class="theme-admonition theme-admonition-info alert alert--info">
        <div class="admonitionHeading_Gvgb"><span></span>info</div>
        <div class="admonitionContent_BuS1">
          <p>Read <a href="https://example.com/win">Install Node.js on\nWindows</a> for details.</p>
        </div>
      </div>
    </main></body></html>
    """

    md = extract_markdown(html, method="dom-markdownify")

    assert "```bash\nnpm install -g @elgato/cli\n```" in md
    assert "> **info**" in md
    assert "> Read [Install Node.js on Windows](https://example.com/win) for details." in md


def test_extract_markdown_unsupported_method_raises():
    with pytest.raises(ValueError, match="Unsupported extractor method"):
        extract_markdown("<p>hi</p>", method="unknown")  # type: ignore[arg-type]


def test_extract_markdown_empty_input():
    md = extract_markdown("   ")

    assert md == ""


def test_extract_page_metadata_prefers_h1_and_meta_description():
    md = "# Getting Started\n\nFallback paragraph text."

    meta = extract_page_metadata(SAMPLE_DOCUSAURUS_HTML, md)

    assert meta.title == "Getting Started"
    assert meta.description == "Learn how to install and configure Example SDK in minutes."


def test_extract_page_metadata_falls_back_to_first_paragraph():
    html = "<html><head><title>API Reference | MySite</title></head><body></body></html>"
    md = "\n".join(
        [
            "```python",
            "print('ignore code')",
            "```",
            "",
            "- list item",
            "",
            "This is the [first](https://example.com) paragraph with **bold** text.",
        ]
    )

    meta = extract_page_metadata(html, md)

    assert meta.title == "API Reference"
    assert meta.description == "This is the first paragraph with bold text."


def test_extract_sidebar_links_extracts_ordered_same_host_links():
    base_url = "https://docs.example.com/docs/sdk/getting-started"

    links = extract_sidebar_links(SAMPLE_DOCUSAURUS_HTML, base_url)

    assert links == [
        "https://docs.example.com/docs/intro",
        "https://docs.example.com/docs/sdk/getting-started",
        "https://docs.example.com/docs/sdk/actions",
    ]
