from __future__ import annotations

from web2md.extractors import (
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


def test_extract_markdown_removes_page_chrome_and_keeps_content():
    html = SAMPLE_DOCUSAURUS_HTML

    md = extract_markdown(html, url="https://docs.example.com/docs/sdk/getting-started")

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


def test_extract_markdown_falls_back_to_article_without_main_landmark():
    html = """
    <html><head><title>Guide | Docs</title></head>
    <body>
      <header><nav><a href="/">Top</a></nav></header>
      <article>
        <h1>Guide</h1>
        <p>This guide explains how to crawl technical documentation.</p>
      </article>
      <aside><h2>Related Posts</h2></aside>
    </body></html>
    """

    md = extract_markdown(html, url="https://docs.example.com/guide")

    assert md == "# Guide\n\nThis guide explains how to crawl technical documentation."


def test_extract_markdown_supports_nested_code_lang_admonition_and_multiline_links():
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

    md = extract_markdown(html)

    assert "```bash\nnpm install -g @elgato/cli\n```" in md
    assert "> **info**" in md
    assert "> Read [Install Node.js on Windows](https://example.com/win) for details." in md


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

    md = extract_markdown(html, url="https://docs.example.com/v1/guide/start/")

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

    md = extract_markdown(html, url="https://developer.mozilla.org/en-US/docs/RegExp")

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

    vp_md = extract_markdown(vitepress_html)
    zen_md = extract_markdown(zensical_html)

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


def test_extract_markdown_keeps_empty_link_like_code_intact():
    html = """
    <html><body><main>
      <h1>Sort</h1>
      <pre><code class="language-cpp">std::sort(v.begin(), v.end(), [](int a, int b) { return a &lt; b; });</code></pre>
      <p>Pass a lambda such as <code>[](int x)</code>.</p>
    </main></body></html>
    """

    md = extract_markdown(html)

    assert "std::sort(v.begin(), v.end(), [](int a, int b) { return a < b; });" in md
    assert "`[](int x)`" in md


def test_extract_markdown_drops_icon_only_links():
    html = """
    <html><body><main>
      <h1>Title</h1>
      <p>See the source <a href="https://github.com/org/repo"><svg><path d="M0 0"/></svg></a> or
      <a href="/logo"><img src="/logo.png" alt="Logo"></a>.</p>
    </main></body></html>
    """

    md = extract_markdown(html, url="https://docs.example.com/")

    assert "github.com" not in md
    assert '[<img src="https://docs.example.com/logo.png" alt="Logo">](/logo)' in md


def test_extract_markdown_preserves_blank_lines_and_indentation_inside_code_blocks():
    html = (
        "<html><body><main><h1>Code</h1>"
        '<pre><code class="language-python">def a():\n    pass\n\n\ndef b():\n    pass</code></pre>'
        "</main></body></html>"
    )

    md = extract_markdown(html)

    assert "```python\ndef a():\n    pass\n\n\ndef b():\n    pass\n```" in md


def test_extract_markdown_collapses_blank_lines_in_prose():
    html = "<html><body><main><h1>Title</h1><div><div><p>One</p></div></div><div><p>Two</p></div></main></body></html>"

    md = extract_markdown(html)

    assert md == "# Title\n\nOne\n\nTwo"


def test_extract_markdown_keeps_line_breaks_as_backslash_breaks():
    html = "<html><body><main><h1>Address</h1><p>Line one<br>Line two</p></main></body></html>"

    md = extract_markdown(html)

    assert "Line one\\\nLine two" in md


def test_extract_markdown_joins_code_lines_wrapped_in_block_elements():
    docusaurus_html = """
    <html><body><main><h1>Run</h1>
      <pre class="prism-code language-bash"><code><div class="token-line"><span>cd my-website</span><br></div><div class="token-line"><span>npm run start</span><br></div></code></pre>
    </main></body></html>
    """
    expressive_code_html = """
    <html><body><main><h1>Run</h1>
      <pre data-language="js"><code><div class="ec-line"><div class="code"><span>const a = 1;</span></div></div><div class="ec-line"><div class="code"><span>const b = 2;</span></div></div></code></pre>
    </main></body></html>
    """

    docusaurus_md = extract_markdown(docusaurus_html)
    expressive_code_md = extract_markdown(expressive_code_html)

    assert "```bash\ncd my-website\nnpm run start\n```" in docusaurus_md
    assert "```js\nconst a = 1;\nconst b = 2;\n```" in expressive_code_md


def test_extract_markdown_lengthens_fence_for_code_containing_backtick_fences():
    html = (
        "<html><body><main><h1>Docs</h1>"
        '<pre><code class="language-markdown">```python\nprint(1)\n```</code></pre>'
        "<p>After.</p></main></body></html>"
    )

    md = extract_markdown(html)

    assert "````markdown\n```python\nprint(1)\n```\n````" in md
    assert md.endswith("After.")


def test_extract_markdown_keeps_every_tab_panel_with_its_label():
    html = """
    <html><body><main>
      <h1>Install</h1>
      <div class="tabs-container">
        <ul role="tablist"><li role="tab" aria-selected="true">npm</li><li role="tab">Yarn</li></ul>
        <div>
          <div role="tabpanel"><pre><code class="language-bash">npm install foo</code></pre></div>
          <div role="tabpanel" hidden=""><pre><code class="language-bash">yarn add foo</code></pre></div>
        </div>
      </div>
      <p hidden>Hidden note</p>
    </main></body></html>
    """

    md = extract_markdown(html)

    assert "**npm**\n\n```bash\nnpm install foo\n```" in md
    assert "**Yarn**\n\n```bash\nyarn add foo\n```" in md
    assert "- npm" not in md
    assert "Hidden note" not in md


def test_extract_markdown_converts_starlight_asides_to_blockquotes():
    html = """
    <html><body><main>
      <h1>Guide</h1>
      <aside aria-label="Caution" class="starlight-aside starlight-aside--caution">
        <p class="starlight-aside__title" aria-hidden="true"><svg><path d="M0 0"/></svg>Caution</p>
        <div class="starlight-aside__content"><p>Do not delete the lock file.</p></div>
      </aside>
      <aside class="right-sidebar"><p>On this page</p></aside>
    </main></body></html>
    """

    md = extract_markdown(html)

    assert "> **Caution**\n>\n> Do not delete the lock file." in md
    assert "On this page" not in md


def test_extract_markdown_keeps_section_headers_and_drops_navigation_headers():
    html = """
    <html><body><main>
      <header><nav><a href="/">Home</a></nav><h2>Site menu</h2></header>
      <h1>Doc</h1>
      <section><header><h2>Section title</h2><p>Lead text.</p></header><p>Body text.</p></section>
      <header><p>Updated yesterday</p></header>
    </main></body></html>
    """

    md = extract_markdown(html)

    assert "## Section title\n\nLead text.\n\nBody text." in md
    assert "Site menu" not in md
    assert "Updated yesterday" not in md


def test_extract_markdown_detects_sphinx_code_language():
    html = """
    <html><body><div role="main">
      <h1>API</h1>
      <div class="highlight-python notranslate"><div class="highlight"><pre><span></span>import os</pre></div></div>
      <div class="highlight-default notranslate"><div class="highlight"><pre>plain output</pre></div></div>
    </div></body></html>
    """

    md = extract_markdown(html)

    assert "```python\nimport os\n```" in md
    assert "```\nplain output\n```" in md


def test_extract_markdown_ignores_locale_class_on_code_block_ancestors():
    html = '<html><body><main class="lang-ja"><h1>X</h1><pre><code>plain text</code></pre></main></body></html>'

    md = extract_markdown(html)

    assert "```\nplain text\n```" in md


def test_extract_markdown_prefers_real_image_url_over_lazy_loading_placeholder():
    html = """
    <html><body><main>
      <h1>Images</h1>
      <p><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" data-src="/img/real.png" alt="Lazy"></p>
      <p><img srcset="/img/small.png 1x, /img/large.png 2x" alt="Responsive"></p>
      <p><img src="data:image/png;base64,iVBORw0KGgo=" alt="Inline"></p>
    </main></body></html>
    """

    md = extract_markdown(html, url="https://docs.example.com/guide")

    assert '<img src="https://docs.example.com/img/real.png" alt="Lazy">' in md
    assert '<img src="https://docs.example.com/img/small.png" alt="Responsive">' in md
    assert '<img src="data:image/png;base64,iVBORw0KGgo=" alt="Inline">' in md


def test_extract_page_metadata_strips_markup_from_title():
    md = '# Guide <img src="https://example.com/badge.svg" alt=""> `foo()` [link](/x) for snake\\_case\n\nBody.'

    meta = extract_page_metadata("", md)

    assert meta.title == "Guide foo() link for snake_case"


def test_extract_page_metadata_uses_first_paragraph_starting_with_emphasis_or_dash():
    bold_md = "# T\n\n- list item\n\n**Important:** read this first.\n\nSecond paragraph."
    dash_md = "# T\n\n---\n\n--verbose enables logging.\n\nSecond paragraph."

    bold_meta = extract_page_metadata("", bold_md)
    dash_meta = extract_page_metadata("", dash_md)

    assert bold_meta.description == "Important: read this first."
    assert dash_meta.description == "--verbose enables logging."


def test_extract_markdown_keeps_standard_link_syntax_when_text_matches_href():
    html = (
        "<html><body><main>"
        '<p>See <a href="guide.html">guide.html</a>, '
        '<a href="/docs/api">/docs/api</a>, and '
        '<a href="https://example.org/x">https://example.org/x</a>.</p>'
        "</main></body></html>"
    )

    md = extract_markdown(html, url="https://example.org/docs/intro")

    assert "[guide.html](guide.html)" in md
    assert "[/docs/api](/docs/api)" in md
    assert "[https://example.org/x](https://example.org/x)" in md


def test_extract_page_metadata_ignores_site_name_heading_outside_main_content():
    html = """
    <html><head><title>Real Page Title | Site</title></head><body>
      <header><h1>Site Name</h1></header>
      <main><h2>Section</h2><p>Body text.</p></main>
    </body></html>
    """
    md = extract_markdown(html)

    meta = extract_page_metadata(html, md)

    assert meta.title == "Real Page Title"
