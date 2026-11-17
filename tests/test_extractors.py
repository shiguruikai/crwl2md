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
            "[Next Actions](https://docs.example.com/docs/sdk/actions)",
        ]
    )

    md = extract_markdown(SAMPLE_DOCUSAURUS_HTML, method="crawl4ai", crawl4ai_markdown=raw_c4ai)

    assert md.startswith("# Getting Started\n")
    assert "Body paragraph here." in md
    assert "[Next Actions](https://docs.example.com/docs/sdk/actions)" in md
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


def test_extract_markdown_preserves_images_as_html_img_tags():
    html = """
    <html><body><main>
      <h1>Guide <img src="/img/badge.svg" alt=""></h1>
      <p><img data-src="../../assets/diagram.png" alt="Diagram" title="Architecture" width="640" height="360"></p>
      <p>Icon without alt text: <img src="icons/warn.png"></p>
      <table>
        <thead><tr><th>Preview</th></tr></thead>
        <tbody><tr><td><img src="/img/cell.png" alt="Cell preview" /></td></tr></tbody>
      </table>
    </main></body></html>
    """

    md = extract_markdown(html, url="https://docs.example.com/v1/guide/start/", method="dom-markdownify")

    assert '# Guide <img src="https://docs.example.com/img/badge.svg" alt="">' in md
    assert (
        '<img src="https://docs.example.com/v1/assets/diagram.png" alt="Diagram" title="Architecture" width="640" height="360">'
        in md
    )
    assert '<img src="https://docs.example.com/v1/guide/start/icons/warn.png">' in md
    assert '| <img src="https://docs.example.com/img/cell.png" alt="Cell preview"> |' in md


def test_extract_markdown_handles_mdn_patterns():
    html = """
    <html><body>
      <main id="content" class="layout__content">
        <div class="translation-banner notecard note"><p>Translated notice</p></div>
        <h1>Regular expressions</h1>
        <aside class="layout__right-sidebar"><nav><h2>On this page</h2></nav></aside>
        <section>
          <h2 id="syntax" class="heading"><a class="heading-anchor" href="#syntax">Syntax</a></h2>
          <p>See <a href="/en-US/docs/Guide">the guide</a> for details.</p>
          <div class="notecard note"><p><strong>Note:</strong> Regular expressions use patterns.</p></div>
          <div class="code-example">
            <div class="example-header"><span class="language-name">js</span></div>
            <pre class="brush: js notranslate"><code>const re = /ab+c/g;</code></pre>
          </div>
        </section>
        <section class="content-section article-footer"><h2>Help improve MDN</h2></section>
      </main>
    </body></html>
    """

    md = extract_markdown(html, url="https://developer.mozilla.org/en-US/docs/RegExp", method="dom-markdownify")

    assert "Translated notice" not in md
    assert "On this page" not in md
    assert "Help improve MDN" not in md
    assert "## Syntax" in md
    assert "## [Syntax]" not in md
    assert "> **Note:** Regular expressions use patterns." in md
    assert "```js\nconst re = /ab+c/g;\n```" in md
    assert "\njs\n\n```js" not in md


def test_extract_markdown_handles_vitepress_and_zensical_containers():
    vitepress_html = """
    <html><body><main>
      <div class="vp-doc">
        <h1>CLI <a class="header-anchor" href="#cli">\u200b</a></h1>
        <div class="custom-block tip">
          <p class="custom-block-title">TIP</p>
          <p>Run vitepress dev.</p>
        </div>
        <div class="language-sh">
          <button class="copy"></button>
          <span class="lang">sh</span>
          <pre class="shiki"><code>vitepress dev</code></pre>
        </div>
      </div>
      <footer class="VPDocFooter"><a class="edit-link">Edit this page</a></footer>
    </main></body></html>
    """
    zensical_html = """
    <html><body><main class="md-main">
      <div class="md-sidebar md-sidebar--primary"><a href="/other">Other</a></div>
      <div class="md-content">
        <nav class="md-path"><a href="/">Home</a></nav>
        <article class="md-content__inner">
          <a href="https://github.com/org/repo/edit/main/doc.md" class="md-content__button">Edit this page</a>
          <h1>Create site<a class="headerlink" href="#create-site" title="Permanent link">¶</a></h1>
          <p>Bootstrap your docs.</p>
        </article>
      </div>
    </main></body></html>
    """

    vp_md = extract_markdown(vitepress_html, method="dom-markdownify")
    zen_md = extract_markdown(zensical_html, method="dom-markdownify")

    assert vp_md.startswith("# CLI\n")
    assert "> **TIP**\n>\n> Run vitepress dev." in vp_md
    assert "```sh\nvitepress dev\n```" in vp_md
    assert "\nsh\n\n```sh" not in vp_md
    assert "Edit this page" not in vp_md

    assert zen_md == "# Create site\n\nBootstrap your docs."


def test_extract_page_metadata_preserves_snake_case_and_ignores_img_tags():
    html = "<html><head><title>Config | Docs</title></head><body></body></html>"
    md = "\n".join(
        [
            '<img src="https://example.com/banner.png" alt="Banner">',
            "",
            'Use `max_depth` <img src="https://example.com/icon.png" alt=""> to configure crawling.',
        ]
    )

    meta = extract_page_metadata(html, md)

    assert meta.title == "Config"
    assert meta.description == "Use max_depth to configure crawling."
