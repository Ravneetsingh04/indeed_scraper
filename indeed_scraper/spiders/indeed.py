import scrapy
from urllib.parse import urlencode, urlparse
import os

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")

# 👇 Configure how many ScraperAPI calls you want to allow per workflow run
MAX_API_CALLS = 5

def get_proxy_url(url):
    payload = {
        "api_key": API_KEY,
        "url": url,
        "render": "true"
    }
    return "https://api.scraperapi.com/?" + urlencode(payload)


class IndeedSpider(scrapy.Spider):
    name = "indeed"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pageCount = 0
        self.api_calls = 0  # ✅ Track total ScraperAPI calls

    def start_requests(self):
        search_query = "AI Developer"
        search_location = "New York, NY"
        indeed_url = f"https://www.indeed.com/jobs?q={search_query}&l={search_location}"
        yield from self.make_api_request(indeed_url, self.parse)

    # ✅ Wrapper for all ScraperAPI requests
    def make_api_request(self, url, callback, **kwargs):
        if self.api_calls >= MAX_API_CALLS:
            self.log(f"⛔ API limit reached ({self.api_calls}/{MAX_API_CALLS}) — stopping further requests.")
            return

        self.api_calls += 1
        self.log(f"📡 API Call #{self.api_calls}: {url}")

        yield scrapy.Request(
            get_proxy_url(url),
            callback=callback,
            errback=self.handle_error,
            **kwargs
        )

    def parse(self, response):
        self.pageCount += 1
        self.log(f"--- Fetched page {self.pageCount}: {response.url} (status {response.status})")

        job_cards = response.css('div.job_seen_beacon')
        self.log(f"Found {len(job_cards)} job cards")

        for card in job_cards[:5]:  # 👈 limit detail requests per page to avoid quota burn
            title = card.css('h2.jobTitle span::text').get()
            company = card.css('span.companyName::text').get()
            location = card.css('div.companyLocation::text').get()
            salary = card.css('div.salary-snippet-container span::text').get()

            job_url = card.css('h2.jobTitle a::attr(href)').get()
            if not job_url:
                continue

            if job_url.startswith("/rc/clk") or job_url.startswith("/pagead/clk"):
                job_url = f"https://www.indeed.com{job_url}"

            yield from self.make_api_request(
                job_url,
                self.parse_details,
                meta={
                    "title": title,
                    "company": company,
                    "location": location,
                    "salary": salary
                }
            )

        # Pagination (only if we still have quota left)
        if self.api_calls < MAX_API_CALLS:
            next_page = response.css('a[aria-label="Next Page"]::attr(href)').get()
            if next_page:
                next_url = response.urljoin(next_page)
                yield from self.make_api_request(next_url, self.parse)

    def parse_details(self, response):
        self.log(f"Parsing details page: {response.url} (status {response.status})")
        desc_parts = response.css('#jobDescriptionText ::text').getall()
        description = " ".join(part.strip() for part in desc_parts if part.strip())

        yield {
            "title": response.meta.get("title"),
            "company": response.meta.get("company"),
            "location": response.meta.get("location"),
            "salary": response.meta.get("salary"),
            "description": description,
            "url": response.url,
        }

    def handle_error(self, failure):
        self.log(f"❌ Request failed: {failure.request.url}")

    def closed(self, reason):
        self.log(f"🧾 Total ScraperAPI calls made: {self.api_calls}")
        if self.api_calls > MAX_API_CALLS:
            self.log(f"⚠️ Limit exceeded: {self.api_calls}/{MAX_API_CALLS}")
