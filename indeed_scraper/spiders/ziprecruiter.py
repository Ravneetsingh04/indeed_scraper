import scrapy
from urllib.parse import urlencode
import os
from datetime import datetime
import inspect

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 5


def get_proxy_url(url):
    """Optimized proxy wrapper (similar to Indeed spider)."""
    payload = {
        "api_key": API_KEY,
        "url": url,
        "country_code": "us",
        "render": "false",          # ✅ Disable JS rendering (ZipRecruiter is static)
        "premium": "false",
        "num_retries": 0,
        "cache": "true",
        "follow_redirect": "false",
        "keep_headers": "true",
    }
    return "https://api.scraperapi.com/?" + urlencode(payload)


class ZipRecruiterSpider(scrapy.Spider):
    name = "ziprecruiter"

    custom_settings = {
        "RETRY_ENABLED": False,
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "CLOSESPIDER_PAGECOUNT": MAX_API_CALLS,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_calls = 0
        self.pageCount = 0
        self.seen_urls = set()

    def start_requests(self):
        search_query = "Salesforce Developer"
        search_location = "New York, NY"

        # ✅ Limit to last 24 hours
        zr_url = (
            f"https://www.ziprecruiter.com/jobs-search?"
            f"search={search_query.replace(' ', '+')}"
            f"&location={search_location.replace(' ', '+')}"
            f"&days=1"
        )
        yield from self.make_api_request(zr_url, self.parse)

    def make_api_request(self, url, callback, **kwargs):
        """Make ScraperAPI call with strict limit and debugging info."""
        if self.api_calls >= MAX_API_CALLS:
            self.log(f"⛔ API limit reached ({self.api_calls}/{MAX_API_CALLS}). Stopping crawl.")
            return

        self.api_calls += 1
        self.log(f"📡 API Call #{self.api_calls}: {url}")
        stack = [f"{frame.function}()" for frame in inspect.stack()[1:4]]
        self.log(f"🧭 Call triggered from: {' → '.join(stack)}")

        yield scrapy.Request(
            get_proxy_url(url),
            callback=callback,
            errback=self.handle_error,
            dont_filter=True,
            meta={
                "dont_redirect": True,
                "handle_httpstatus_list": [301, 302, 303, 307, 308],
            },
            **kwargs,
        )

    def parse(self, response):
        self.pageCount += 1
        if self.api_calls > 1:
            self.log("⛔ Preventing further requests (single-call mode enforced)")
            return

        self.log(f"✅ Fetched page {self.pageCount}: {response.url} (status {response.status})")

        job_cards = response.css("div.flex.flex-col")
        if not job_cards:
            self.log("⚠ No job cards found — check HTML structure.")
            return

        self.log(f"✅ Found {len(job_cards)} job cards on first page.")

        for card in job_cards[:5]:  # Limit jobs to 5 like Indeed
            title = (
                card.css("h2::text").get()
                or card.css("h2[aria-label]::attr(aria-label)").get()
                or card.css("button[aria-label]::attr(aria-label)").get()
            )
            company = (card.css("a[data-testid='job-card-company']::text").get() or "").strip() or "Unknown company"

            location_parts = card.css("a[data-testid='job-card-location']::text, p span::text").getall()
            location = " ".join(p.strip() for p in location_parts if p.strip()) or "Not specified"

            salary_parts = card.css(
                "span[data-testid='job-card-salary']::text, "
                "div[data-testid='salary_estimate']::text, "
                "span[data-testid='estimated-salary']::text"
            ).getall()
            salary = " ".join(p.strip() for p in salary_parts if p.strip()) or "Not disclosed"

            job_url = card.css("a[data-testid='job-card-company']::attr(href)").get()
            if job_url and job_url.startswith("/"):
                job_url = f"https://www.ziprecruiter.com{job_url}"

            if not job_url or job_url in self.seen_urls:
                continue

            self.seen_urls.add(job_url)

            yield {
                "title": (title or "").strip(),
                "company": company,
                "location": location,
                "salary": salary,
                "posted": datetime.now().strftime("%Y-%m-%d"),
                "url": job_url,
            }

        self.log(f"📌 Yielded {len(self.seen_urls)} total jobs.")
        self.log("✅ Completed single batch scrape (no pagination).")

    def handle_error(self, failure):
        self.log(f"❌ Request failed: {failure.request.url}")

    def closed(self, reason):
        self.log(f"🧾 Total ScraperAPI calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
        self.log(f"🚪 Spider closed due to: {reason}")
