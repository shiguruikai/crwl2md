"""web2md パッケージ。"""

from web2md.crawler import CrawlConfig, CrawlSummary, convert_single, crawl_site, crawl_site_sync
from web2md.extractors import ExtractorType, extract_markdown

__all__ = [
    "CrawlConfig",
    "CrawlSummary",
    "ExtractorType",
    "__version__",
    "convert_single",
    "crawl_site",
    "crawl_site_sync",
    "extract_markdown",
]

__version__ = "0.1.0"
