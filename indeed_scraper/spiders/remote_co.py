import scrapy
from urllib.parse import urlencode, urljoin
import os
from datetime import datetime

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 3  # Remote.co is light, so a few API calls max


def get_proxy_url(url):
    """Use ScraperAPI efficiently — no render required since Remote.co is mostly static."""
    payload = {
        "api_key": API_KEY,
        "url": url,
        "country_code": "us",
        "render": "false",
        "premium": "false",
        "num_retries": 1,
        "cache": "true",
    }
    return "https://api.scraperapi.com/?" + urlencode(payload)


class RemoteCoSpider(scrapy.Spider):
    name = "remote_co"

    custom_settings = {
        "RETRY_ENABLED": False,
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "CLOSESPIDER_PAGECOUNT": 3,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_calls = 0
        self.page_count = 0
        self.visited_pages = set()
        self.seen_urls = set()

    def start_requests(self):
        query = "salesforce developer"
        start_url = f"https://remote.co/remote-jobs/search/?search_keywords={query.replace(' ', '+')}"
        yield from self.make_api_request(start_url, self.parse)

    def make_api_request(self, url, callback, **kwargs):
        if self.api_calls >= MAX_API_CALLS:
            self.log(f"⛔ API limit reached ({self.api_calls}/{MAX_API_CALLS}). Stopping crawl.")
            return

        self.api_calls += 1
        self.log(f"📡 API Call #{self.api_calls}: {url}")

        target = get_proxy_url(url)
        yield scrapy.Request(
            target,
            callback=callback,
            errback=self.handle_error,
            dont_filter=True,
            meta={"dont_redirect": True},
            **kwargs,
        )

    def parse(self, response):
        self.page_count += 1
        self.log(f"✅ Fetched page {self.page_count}: {response.url} (status {response.status})")

        job_cards = response.css("div.card")  # Remote.co uses div.card for job entries

        if not job_cards:
            self.log("⚠ No job cards found — check HTML structure or blocking")
            return
        else:
            self.log(f"✅ Found {len(job_cards)} job cards.")

        items_scraped = 0
        for card in job_cards[:30]:
            href = card.css("a.card__job-link::attr(href)").get()
            if not href:
                continue

            job_url = urljoin("https://remote.co", href)
            if job_url in self.seen_urls:
                continue
            self.seen_urls.add(job_url)

            title = card.css("span.card__job-title::text").get()
            company = card.css("span.card__company::text").get()
            location = card.css("span.card__location::text").get()
            posted = card.css("time::attr(datetime)").get() or datetime.now().strftime("%Y-%m-%d")
            job_type = card.css("span.card__job-type::text").get() or "Not specified"

            yield {
                "title": (title or "").strip(),
                "company": (company or "").strip(),
                "location": (location or "").strip(),
                "posted": posted.strip(),
                "type": job_type.strip(),
                "url": job_url,
            }
            items_scraped += 1

        self.log(f"📌 Items yielded from page: {items_scraped}")

        # Pagination
        next_page = response.css("a.next.page-numbers::attr(href)").get()
        if next_page and self.api_calls < MAX_API_CALLS:
            next_url = urljoin("https://remote.co", next_page)
            if next_url not in self.visited_pages:
                self.visited_pages.add(next_url)
                yield from self.make_api_request(next_url, self.parse)

    def handle_error(self, failure):
        req = getattr(failure, "request", None)
        url = req.url if req is not None else "unknown"
        self.log(f"❌ Request failed: {url}")

    def closed(self, reason):
        self.log(f"🧾 Total API calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
