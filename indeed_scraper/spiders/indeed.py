import scrapy
from urllib.parse import urlencode
import os

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 5  # 👈 Set max allowed ScraperAPI requests per workflow run

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
        self.api_calls = 0  # ✅ Track ScraperAPI usage

    def start_requests(self):
        search_query = "AI Developer"
        search_location = "New York, NY"
        indeed_url = f"https://www.indeed.com/jobs?q={search_query}&l={search_location}"
        yield from self.make_api_request(indeed_url, self.parse)

    def make_api_request(self, url, callback, **kwargs):
        """Wrapper that enforces API call limits."""
        if self.api_calls >= MAX_API_CALLS:
            self.log(f"⛔ API limit reached ({self.api_calls}/{MAX_API_CALLS}). Stopping crawl.")
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

        for card in job_cards[:5]:  # 👈 Limit how many detail pages to visit per list page
            title = card.css('h2.jobTitle span::text').get()
            company = card.css('span.companyName::text').get()
            location = card.css('div.companyLocation::text').get()
            salary = card.css('div.salary-snippet-container span::text').get()
            job_url = card.css('h2.jobTitle a::attr(href)').get()

            if not job_url:
                continue

            if job_url.startswith("/"):
                job_url = f"https://www.indeed.com{job_url}"

            # Use cb_kwargs to safely pass values to the detail parser
            yield from self.make_api_request(
                job_url,
                self.parse_details,
                cb_kwargs={
                    "title": title or "",
                    "company": company or "",
                    "location": location or "",
                    "salary": salary or ""
                }
            )

        # Pagination — only if limit not hit
        if self.api_calls < MAX_API_CALLS:
            next_page = response.css('a[aria-label="Next Page"]::attr(href)').get()
            if next_page:
                next_url = response.urljoin(next_page)
                yield from self.make_api_request(next_url, self.parse)

    # def parse_details(self, response, title, company, location, salary):
    #     self.log(f"Parsing details page: {response.url} (status {response.status})")

    #     desc_parts = response.css('#jobDescriptionText ::text').getall()
    #     description = " ".join(part.strip() for part in desc_parts if part.strip())

    #     yield {
    #         "title": title.strip(),
    #         "company": company.strip(),
    #         "location": location.strip(),
    #         "salary": salary.strip(),
    #         "description": description,
    #         "url": response.url,
    #     }

    def parse_details(self, response, title="", company="", location="", salary=""):
        self.log(f"Parsing details page: {response.url} (status {response.status})")
    
        # Extract again from job page (these are Indeed selectors that work reliably)
        title_detail = response.css('h1.jobsearch-JobInfoHeader-title::text').get()
        company_detail = response.css('div.jobsearch-InlineCompanyRating div::text').get()
        location_detail = response.css('div.jobsearch-JobInfoHeader-subtitle div::text').get()
        salary_detail = response.css('div.salary-snippet-container span::text').get()
    
        # Fallback: use passed-in values if detail selectors failed
        title = title_detail or title
        company = company_detail or company
        location = location_detail or location
        salary = salary_detail or salary
    
        # Extract job description
        desc_parts = response.css('#jobDescriptionText ::text').getall()
        description = " ".join(part.strip() for part in desc_parts if part.strip())
    
        yield {
            "title": (title or "").strip(),
            "company": (company or "").strip(),
            "location": (location or "").strip(),
            "salary": (salary or "").strip(),
            "description": description,
            "url": response.url,
        }


    def handle_error(self, failure):
        self.log(f"❌ Request failed: {failure.request.url}")

    def closed(self, reason):
        """When spider finishes, log API usage summary."""
        self.log(f"🧾 Total ScraperAPI calls made: {self.api_calls}/{MAX_API_CALLS}")
