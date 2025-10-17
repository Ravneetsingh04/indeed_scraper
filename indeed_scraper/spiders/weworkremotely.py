import scrapy
from urllib.parse import urlencode, urljoin
import os
from datetime import datetime

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 5



def get_proxy_url(url):
    """Build ScraperAPI URL with conservative parameters to reduce backend retries/credits."""
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


class WeWorkRemotelySpider(scrapy.Spider):
    name = "weworkremotely"

    custom_settings = {
        "RETRY_ENABLED": False,
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "CLOSESPIDER_PAGECOUNT": 5,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_calls = 0
        self.page_count = 0
        self.visited_pages = set()
        self.seen_urls = set()

    def start_requests(self):
        query = "rails developer"
        # Add the 'Past 24 Hours' filter to the search URL
        start_url = f"https://weworkremotely.com/remote-jobs/search?term={query.replace(' ', '+')}&sort=Past+24+Hours"
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
        self.log(f"--- Fetched page {self.page_count}: {response.url} (status {response.status})")

        # WWR common patterns: job listings are anchors under job lists; fallback selectors included
        job_cards = response.css("li.new-listing-container:not(.feature--ad)")

        if not job_cards:
            self.log("⚠ No job cards found — check HTML structure or blocking")
            return
        else:
            self.log(f"✅ Found {len(job_cards)} job cards (raw).")

        items_scraped = 0
        for card in job_cards[:30]:
            # The `card` might be <article> or <li> or <a> — find the link first
            href = card.css("a[href^='/remote-jobs/']::attr(href)").get()
            if not href:
                continue
            # Build absolute URL
            job_url = urljoin("https://weworkremotely.com", href)

            # Skip duplicates
            if job_url in self.seen_urls:
                continue
            self.seen_urls.add(job_url)

            # Title, company, location, date
            title = card.css("h3.new-listing__header__title::text").get()
            company = card.css("p.new-listing__company-name::text").get()
            location = card.css("p.new-listing__company-headquarters::text").get()
            posted = card.css("p.new-listing__header__icons__date::text").get()
            posted = posted.strip() if posted else datetime.now().strftime("%Y-%m-%d")
            categories = card.css("div.new-listing__categories p::text").getall()
            salary = next((c.strip() for c in categories if "$" in c), "Not disclosed")

            

            yield {
                "title": (title or "").strip(),
                "company": (company or "").strip(),
                "location": (location or "").strip(),
                "posted": posted,
                "salary": salary,
                "url": job_url,
            }
            items_scraped += 1

        self.log(f"📌 Items yielded from page: {items_scraped}")

         # Pagination (if any)
        next_page = response.css("a[rel='next']::attr(href)").get()
        if next_page and self.api_calls < MAX_API_CALLS:
            next_url = urljoin("https://weworkremotely.com", next_page)
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
