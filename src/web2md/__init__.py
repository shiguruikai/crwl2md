from importlib.metadata import version

from web2md.crawler import (
    BrowserNotInstalledError,
    CrawlConfig,
    CrawlSummary,
    FailedPage,
    convert_single,
    convert_single_sync,
    crawl_site,
    crawl_site_sync,
    install_browser,
)
from web2md.extractors import extract_markdown
from web2md.site_builder import FRONTMATTER_FIELDS, FrontmatterField

__all__ = [
    "FRONTMATTER_FIELDS",
    "BrowserNotInstalledError",
    "CrawlConfig",
    "CrawlSummary",
    "FailedPage",
    "FrontmatterField",
    "__version__",
    "convert_single",
    "convert_single_sync",
    "crawl_site",
    "crawl_site_sync",
    "extract_markdown",
    "install_browser",
]

__version__ = version("web2md")
