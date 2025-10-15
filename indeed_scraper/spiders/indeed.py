import scrapy
from urllib.parse import urljoin
import os
from datetime import datetime
from utils.scrapingbee_utils import get_scrapingbee_url
from twisted.internet.error import DNSLookupError, TimeoutError, TCPTimedOutError


MAX_API_CALLS = 5  # adjust as needed


class IndeedSpider(scrapy.Spider):
    name = "indeed"

    # CUSTOM SCRAPY SETTINGS (Disable retries & robots.txt)
    custom_settings = {
        "RETRY_ENABLED": False,          # avoid retrying failed ScrapingBee calls
        "ROBOTSTXT_OBEY": False,         # don't waste credits on robots.txt
        "DOWNLOAD_DELAY": 1,             # polite delay between requests
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "CLOSESPIDER_PAGECOUNT": 5,      # safety stop during testing
        "LOG_LEVEL": "INFO",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pageCount = 0
        self.api_calls = 0
        self.seen_urls = set()
        self.visited_pages = set()  # prevent duplicate pagination

    # ========== START REQUESTS ==========
    def start_requests(self):
        search_query = "Salesforce Developer Deloitte"
        search_location = "New York, NY"
        indeed_url = f"https://www.indeed.com/jobs?q={search_query}&l={search_location}"
        yield from self.make_api_request(indeed_url, self.parse)

    # ========== MAKE SCRAPINGBEE REQUEST ==========
    def make_api_request(self, target_url, callback, render_js=False, premium_proxy=False, wait=None, **kwargs):
        """Handles API call logic for ScrapingBee"""
        if self.api_calls >= MAX_API_CALLS:
            self.log(f"⛔ API limit reached ({self.api_calls}/{MAX_API_CALLS}). Stopping crawl.")
            return

        self.api_calls += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        scrapingbee_url = get_scrapingbee_url(
            target_url,
            render_js=render_js,          # set True only if necessary
            premium_proxy=premium_proxy,
            wait=wait
        )

        # Debug logs
        self.log(f"\n📡 API CALL #{self.api_calls} @ {timestamp}")
        self.log(f"🌐 Target URL: {target_url}")
        self.log(f"🔗 ScrapingBee URL: {scrapingbee_url}")

        yield scrapy.Request(
            scrapingbee_url,
            callback=callback,
            errback=self.handle_error,
            dont_filter=True,                   # prevent filtering same URLs with proxies
            meta={"source_url": target_url},     # store original
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
<<<<<<< HEAD
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"
                )
            },
            **kwargs,
        )

    # ========== PARSE RESPONSE ==========
    def parse(self, response):
        self.pageCount += 1
        self.log(f"--- Fetched page {self.pageCount}: {response.url} (status {response.status})")

        job_cards = response.css('div.job_seen_beacon, a.tapItem')
        if not job_cards:
            self.log("⚠ No job cards found — check HTML structure or try render_js=True.")
        else:
            self.log(f"✅ Found {len(job_cards)} job cards.")

        for card in job_cards[:3]:
            title = (
                card.css("h2.jobTitle span::text").get()
                or card.css("h2 span::text").get()
                or card.css("a[aria-label]::attr(aria-label)").get()
            )
            company = card.css("span.companyName::text, span[data-testid='company-name']::text").get()
            location_parts = card.css(
                "div.companyLocation *::text, div[data-testid='text-location'] *::text"
            ).getall()
            location = " ".join(p.strip() for p in location_parts if p.strip())

            # --- Salary Extraction ---
            salary_parts = card.css(
                "div[id='salaryInfoAndJobType'] span::text, "
                "div[data-testid='attribute_snippet_text']::text, "
                "div[data-testid='jobsearch-OtherJobDetailsContainer'] span::text, "
                "div[data-testid='salary-snippet-container'] span::text, "
                "span.css-1oc7tea::text, "
                "span[data-testid='attribute_snippet_text']::text"
            ).getall()
            salary = " ".join(p.strip() for p in salary_parts if p.strip())

            if not salary:
                salary = card.xpath(
                    ".//*[contains(text(), '$') or contains(text(), 'hour') or contains(text(), 'year')]/text()"
                ).get(default="").strip()

            if not salary:
                salary = "Not disclosed"

            posted = datetime.now().strftime("%Y-%m-%d")
            job_url = card.css("a::attr(href)").get()
            if not job_url:
                continue

            if job_url.startswith("/"):
                job_url = f"https://www.indeed.com{job_url}"

            if job_url in self.seen_urls:
                continue
            self.seen_urls.add(job_url)

            yield {
                "title": (title or "").strip(),
                "company": (company or "").strip(),
                "location": (location or "").strip(),
                "salary": (salary or "").strip(),
                "posted": posted,
                "url": job_url,
            }

        # --- Pagination ---
        if self.api_calls < MAX_API_CALLS:
            next_page = response.css(
                'a[aria-label="Next Page"]::attr(href), a[data-testid="pagination-page-next"]::attr(href)'
            ).get()
            if next_page:
                next_url = urljoin("https://www.indeed.com", next_page)
                if next_url not in self.visited_pages:
                    self.visited_pages.add(next_url)
                    yield from self.make_api_request(next_url, self.parse)
                else:
                    self.log(f"🔁 Skipping duplicate page: {next_url}")

    # ========== HANDLE ERRORS ==========
    def handle_error(self, failure):
        req = getattr(failure, "request", None)
        url = req.meta.get("source_url") if req and req.meta else getattr(req, "url", "unknown")
        self.log(f"❌ Request failed for {url} | error={repr(failure)}")

        if failure.check(DNSLookupError, TimeoutError, TCPTimedOutError):
            if self.api_calls < MAX_API_CALLS:
                self.log("🔁 Retrying transient network error.")
                yield from self.make_api_request(url, self.parse)
            return

        resp = getattr(failure.value, "response", None)
        if resp and resp.status == 403:
            self.log("⛔ ScrapingBee returned 403 — likely credit exhaustion or anti-bot block.")

    # ========== CLOSE LOG ==========
    def closed(self, reason):
        self.log(f"🧾 Total ScrapingBee calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
=======
                    "AppleWebKit/537.36
>>>>>>> 2ae51fd (Initial commit - ScrapingBee integration)
