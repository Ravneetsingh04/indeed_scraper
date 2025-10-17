import scrapy
from urllib.parse import urlencode, urljoin
import os
from datetime import datetime

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 5


def get_proxy_url(url):
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


class IndeedSpider(scrapy.Spider):
    name = "indeed"

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
        self.seen_urls = set()

    def start_requests(self):
        query = "React Developer"
        location = "New York, NY"
        # Add time filter for "last 24 hours" (optional parameter)
        start_url = f"https://www.indeed.com/jobs?q={query.replace(' ', '+')}&l={location.replace(' ', '+')}&fromage=1"
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

        job_cards = response.css('div.job_seen_beacon, a.tapItem')
        if not job_cards:
            self.log("⚠ No job cards found — check structure or blocking.")
            return
        else:
            self.log(f"✅ Found {len(job_cards)} job cards.")

        for card in job_cards:
            title = (
                card.css("h2.jobTitle span::text").get()
                or card.css("h2 span::text").get()
                or card.css("a[aria-label]::attr(aria-label)").get()
            )
            company = card.css("span.companyName::text, span[data-testid='company-name']::text").get()
            location_parts = card.css("div.companyLocation *::text, div[data-testid='text-location'] *::text").getall()
            location = " ".join(p.strip() for p in location_parts if p.strip())

            # Salary extraction
            salary_parts = card.css(
                "div[id='salaryInfoAndJobType'] span::text, "
                "div[data-testid='attribute_snippet_text']::text, "
                "div[data-testid='jobsearch-OtherJobDetailsContainer'] span::text, "
                "div[data-testid='salary-snippet-container'] span::text"
            ).getall()
            salary = " ".join(p.strip() for p in salary_parts if p.strip()) or "Not disclosed"

            posted = datetime.now().strftime("%Y-%m-%d")

            job_url = card.css("a::attr(href)").get()
            if job_url:
                if job_url.startswith("/"):
                    job_url = urljoin("https://www.indeed.com", job_url)
                if job_url not in self.seen_urls:
                    self.seen_urls.add(job_url)
                    yield {
                        "title": (title or "").strip(),
                        "company": (company or "").strip(),
                        "location": (location or "").strip(),
                        "salary": (salary or "").strip(),
                        "posted": posted,
                        "url": job_url,
                    }

        self.log(f"📌 Items yielded from page: {len(self.seen_urls)}")

        # ⚡ No pagination calls — single API hit behavior (like WWR)
        self.log("✅ Completed single batch scrape (no further pagination).")

    def handle_error(self, failure):
        req = getattr(failure, "request", None)
        url = req.url if req is not None else "unknown"
        self.log(f"❌ Request failed: {url}")

    def closed(self, reason):
        self.log(f"🧾 Total API calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
