import scrapy
from urllib.parse import urlencode, urlparse
import os

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")

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
        self.maxPages = 2

    def start_requests(self):
        search_query = "AI Developer"
        search_location = "New York, NY"
        indeed_url = f"https://www.indeed.com/jobs?q={search_query}&l={search_location}"
        yield scrapy.Request(get_proxy_url(indeed_url), callback=self.parse)

    def parse(self, response):
        self.pageCount += 1
        self.log(f"--- Fetched page {self.pageCount}: {response.url} (status {response.status})")

        job_cards = response.css('div.job_seen_beacon')
        self.log(f"Found {len(job_cards)} job cards")

        for card in job_cards:
            title = card.css('h2.jobTitle span::text').get()
            company = card.css('span.companyName::text').get()
            location = card.css('div.companyLocation::text').get()
            salary = card.css('div.salary-snippet-container span::text').get()

            # Extract the relative job link (avoid API redirect URLs)
            job_url = card.css('h2.jobTitle a::attr(href)').get()
            if not job_url:
                continue

            # Ensure we’re using a proper Indeed URL, not a redirect one
            if job_url.startswith("/rc/clk") or job_url.startswith("/pagead/clk"):
                job_url = f"https://www.indeed.com{job_url}"

            full_job_url = job_url

            # ✅ Don’t double-wrap URLs with ScraperAPI if already encoded
            yield scrapy.Request(
                get_proxy_url(full_job_url),
                callback=self.parse_details,
                meta={
                    "title": title,
                    "company": company,
                    "location": location,
                    "salary": salary,
                },
                errback=self.handle_error
            )

        # Pagination
        if self.pageCount < self.maxPages:
            next_page = response.css('a[aria-label="Next Page"]::attr(href)').get()
            if next_page:
                next_url = response.urljoin(next_page)
                yield scrapy.Request(get_proxy_url(next_url), callback=self.parse)

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
        self.log(f"Request failed: {failure.request.url}")
