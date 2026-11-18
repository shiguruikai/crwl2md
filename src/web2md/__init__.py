from importlib.metadata import version

from web2md.crawler import CrawlConfig, CrawlSummary, FailedPage, convert_single, crawl_site, crawl_site_sync
from web2md.extractors import extract_markdown
from web2md.site_builder import FRONTMATTER_FIELDS, FrontmatterField

__all__ = [
    "FRONTMATTER_FIELDS",
    "CrawlConfig",
    "CrawlSummary",
    "FailedPage",
    "FrontmatterField",
    "__version__",
    "convert_single",
    "crawl_site",
    "crawl_site_sync",
    "extract_markdown",
]

__version__ = version("web2md")
