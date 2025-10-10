import scrapy
from urllib.parse import urlencode
import os
import re

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 5  # 👈 Limit ScraperAPI requests per workflow run

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
        self.api_calls = 0
        self.seen_urls = set()  # ✅ To track unique jobs (avoid duplicates)

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

        for card in job_cards[:5]:  # 👈 limit to 5 detail pages per list page
            # Extract job metadata
            title = card.css('h2.jobTitle span::text').get()
            company = card.css('span.companyName::text').get()
            # ✅ Combine multiple lines of location (e.g., “New York, NY” and “Remote”)
            location_parts = card.css('div.companyLocation *::text').getall()
            location = " ".join(part.strip() for part in location_parts if part.strip())
            # location = card.css('div.companyLocation::text').get()
            # Capture all salary text, not just the first span
            salary_parts = card.css('div.salary-snippet-container *::text').getall()
            salary = " ".join(part.strip() for part in salary_parts if part.strip())
            # salary = card.css('div.salary-snippet-container span::text').get()
            posted = card.css('span.date::text, span.jobsearch-HiringInsights-entry--text::text').get()
            job_url = card.css('h2.jobTitle a::attr(href)').get()
            # posted_text = card.css('span.date::text, span.jobsearch-HiringInsights-entry--text::text').get()

            # ✅ Only include jobs posted today or just posted
            # if posted_text:
            #     posted_text = posted_text.lower().strip()
            #     if not ("today" in posted_text or "just" in posted_text):
            #         self.log(f"⏭ Skipping old job ({posted_text}) - {title}")
            #         continue

            if not job_url or not title:
                continue

            if job_url.startswith("/"):
                job_url = f"https://www.indeed.com{job_url}"

            # ✅ Skip duplicates using job URL
            if job_url in self.seen_urls:
                self.log(f"🔁 Skipping duplicate: {job_url}")
                continue
            self.seen_urls.add(job_url)

            # Pass data to detail page
            # yield from self.make_api_request(
            #     job_url,
            #     self.parse_details,
            #     cb_kwargs={
            #         "title": title or "",
            #         "company": company or "",
            #         "location": location or "",
            #         "salary": salary or "",
            #         "posted_text": posted_text or "today",
            #     }
            # )

        # ✅ Only today's or just posted jobs

            if posted:

                posted = posted.lower().strip()

                if not ("today" in posted or "just" in posted):

                    continue

            else:

                posted = "today"



            # ✅ Yield job data directly from list page

            yield {

                "title": (title or "").strip(),

                "company": (company or "").strip(),

                "location": (location or "").strip(),

                "salary": (salary or "").strip(),

                "posted": posted,

                "url": job_url,

            }

        # ✅ Go to next page if limit not reached
        if self.api_calls < MAX_API_CALLS:
            next_page = response.css('a[aria-label="Next Page"]::attr(href)').get()
            if next_page:
                next_url = response.urljoin(next_page)
                yield from self.make_api_request(next_url, self.parse)

    # def parse_details(self, response, title="", company="", location="", salary="", posted_text="today"):
    #     self.log(f"Parsing details page: {response.url} (status {response.status})")

    #     # Extract from detail page
    #     title_detail = response.css('h1.jobsearch-JobInfoHeader-title::text').get()
    #     company_detail = response.css('div.jobsearch-InlineCompanyRating div::text').get()
    #     location_detail = response.css('div.jobsearch-JobInfoHeader-subtitle div::text').get()
    #     salary_detail = response.css('div.salary-snippet-container span::text').get()

    #     desc_parts = response.css('#jobDescriptionText ::text').getall()
    #     description = " ".join(part.strip() for part in desc_parts if part.strip())

    #     # --- Fallback extraction from description text ---
    #     if not location_detail:
    #         match = re.search(r"(?i)(?:Location|Work Location|Based in):\s*([A-Za-z0-9,\-\s()]+)", description)
    #         if match:
    #             location_detail = match.group(1).strip()

    #     if not salary_detail:
    #         match = re.search(r"(?i)(?:Salary|Compensation|Pay|Hourly Range|Annual Pay|Rate):\s*\$?([\w\s\.,\-]+)", description)
    #         if match:
    #             salary_detail = match.group(1).strip()

    #     if not company_detail:
    #         match = re.search(r"(?i)(?:Company|Employer):\s*([A-Za-z0-9&\.\-\s]+)", description)
    #         if match:
    #             company_detail = match.group(1).strip()

    #     # Fallback to passed-in values if still empty
    #     title = title_detail or title
    #     company = company_detail or company
    #     location = location_detail or location
    #     salary = salary_detail or salary

    #     yield {
    #         "title": (title or "").strip(),
    #         "company": (company or "").strip(),
    #         "location": (location or "").strip(),
    #         "salary": (salary or "").strip(),
    #         "posted": (posted_text or "").strip(),
    #         "description": description,
    #         "url": response.url,
    #     }

    def handle_error(self, failure):
        self.log(f"❌ Request failed: {failure.request.url}")

    def closed(self, reason):
        """When spider finishes, log API usage summary."""
        self.log(f"🧾 Total ScraperAPI calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
