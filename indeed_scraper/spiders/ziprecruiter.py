import scrapy
from urllib.parse import urlencode
import os
from datetime import datetime

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 5


def get_proxy_url(url):
    payload = {"api_key": API_KEY, "url": url, "render": "true"}
    return "https://api.scraperapi.com/?" + urlencode(payload)


class ZipRecruiterSpider(scrapy.Spider):
    name = "ziprecruiter"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pageCount = 0
        self.api_calls = 0
        self.seen_urls = set()

        # optionally allow overrides via -a query="..." -a location="..."
        self.query = kwargs.get("query", "AI Developer")
        self.location = kwargs.get("location", "New York, NY")

    def start_requests(self):
        q = self.query.replace(" ", "+")
        loc = self.location.replace(" ", "+")
        zr_url = f"https://www.ziprecruiter.com/candidate/search?search={q}&location={loc}"
        yield from self.make_api_request(zr_url, self.parse)

    def make_api_request(self, url, callback, **kwargs):
        if self.api_calls >= MAX_API_CALLS:
            self.log(f"⛔ API limit reached ({self.api_calls}/{MAX_API_CALLS}). Stopping crawl.")
            return
        self.api_calls += 1
        self.log(f"📡 API Call #{self.api_calls}: {url}")
        yield scrapy.Request(
            get_proxy_url(url),
            callback=callback,
            errback=self.handle_error,
            dont_filter=True,
            **kwargs,
        )

    def parse(self, response):
        self.pageCount += 1
        self.log(f"--- Fetched page {self.pageCount}: {response.url} (status {response.status})")

        # ZR card selectors (multiple fallbacks for resiliency)
        cards = response.css(
            "article.job_result, div.job_result, div.job_content, div[data-testid='job_card']"
        )
        if not cards:
            self.log("⚠ No job cards found — check HTML structure.")
        else:
            self.log(f"✅ Found {len(cards)} job cards.")

        for card in cards[:20]:
            # Title
            title = (
                card.css("a.job_link::text").get()
                or card.css("a[data-testid='job_link']::text").get()
                or card.css("a::text").get()
            )
            title = (title or "").strip()

            # Company
            company = (
                card.css("a.t_org_link::text").get()
                or card.css("div.job_org::text").get()
                or card.css("[data-testid='job-card-company-name']::text").get()
                or card.css("span.company_name::text").get()
            )
            company = (company or "").strip()

            # Location (ZR often has compact location spans/divs)
            loc_parts = card.css(
                "span.job_location::text, div.job_location::text, [data-testid='job-card-location'] *::text"
            ).getall()
            location = " ".join(p.strip() for p in loc_parts if p.strip())

            # Salary
            salary_parts = card.css(
                "span.job_salary::text, div.job_salary::text, [data-testid='job-card-salary'] *::text"
            ).getall()
            salary = " ".join(p.strip() for p in salary_parts if p.strip())

            if not salary:
                # Backup: scan visible text for monetary/time patterns
                salary = card.xpath(
                    ".//*[contains(., '$') or contains(., 'hour') or contains(., 'year') or contains(., 'month')]/text()"
                ).get(default="").strip()
            if not salary:
                salary = "Not disclosed"

            # Posted date (ZR sometimes shows 'X days ago'); default to today for consistency
            posted = datetime.now().strftime("%Y-%m-%d")

            # URL
            href = (
                card.css("a.job_link::attr(href)").get()
                or card.css("a[data-testid='job_link']::attr(href)").get()
                or card.css("a::attr(href)").get()
            )
            if not href:
                continue

            if href.startswith("/"):
                job_url = response.urljoin(href)
            else:
                job_url = href

            if job_url in self.seen_urls:
                continue
            self.seen_urls.add(job_url)

            yield {
                "title": title,
                "company": company,
                "location": location,
                "salary": salary,
                "posted": posted,
                "url": job_url,
            }

        # Pagination
        if self.api_calls < MAX_API_CALLS:
            next_page = response.css(
                "a[rel='next']::attr(href), a.next::attr(href), a.pagination_next::attr(href), "
                "a[aria-label='Next']::attr(href)"
            ).get()
            if next_page:
                next_url = response.urljoin(next_page)
                yield from self.make_api_request(next_url, self.parse)

    def handle_error(self, failure):
        try:
            self.log(f"❌ Request failed: {failure.request.url}")
        except Exception:
            self.log("❌ Request failed (no URL available).")

    def closed(self, reason):
        self.log(f"🧾 Total ScraperAPI calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
