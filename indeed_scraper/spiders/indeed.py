import scrapy
from urllib.parse import urlencode
import os
from datetime import datetime

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 5


def get_proxy_url(url):
    payload = {"api_key": API_KEY, "url": url, "render": "true"}
    return "https://api.scraperapi.com/?" + urlencode(payload)


class IndeedSpider(scrapy.Spider):
    name = "indeed"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pageCount = 0
        self.api_calls = 0
        self.seen_urls = set()

    def start_requests(self):
        search_query = "Python Developer"
        search_location = "New York, NY"
        indeed_url = f"https://www.indeed.com/jobs?q={search_query}&l={search_location}"
        yield from self.make_api_request(indeed_url, self.parse)

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
            **kwargs,
        )

    def parse(self, response):
        self.pageCount += 1
        self.log(f"--- Fetched page {self.pageCount}: {response.url} (status {response.status})")

        # Use both div.job_seen_beacon and attribute fallbacks for reliability
        job_cards = response.css('div.job_seen_beacon, a.tapItem')

        if not job_cards:
            self.log("⚠ No job cards found — check HTML structure.")
        else:
            self.log(f"✅ Found {len(job_cards)} job cards.")

        for card in job_cards[:3]:
            title = (
                card.css("h2.jobTitle span::text").get()
                or card.css("h2 span::text").get()
                or card.css("a[aria-label]::attr(aria-label)").get()
            )
            company = card.css("span.companyName::text, span[data-testid='company-name']::text").get()
            # Capture multiline locations (e.g., "New York, NY" + "Remote")
            location_parts = card.css("div.companyLocation *::text, div[data-testid='text-location'] *::text").getall()
            location = " ".join(p.strip() for p in location_parts if p.strip())
            

            # --- Salary Extraction ---
            # salary_parts = card.css(
            #     "div#salaryInfoAndJobType span::text, "
            #     "div[data-testid='jobsearch-OtherJobDetailsContainer'] span::text, "
            #     "div.salary-snippet-container *::text, "
            #     "div.metadata.salary-snippet-container *::text, "
            #     "span.estimated-salary::text, "
            #     "div[data-testid='attribute_snippet_text']::text"
            # ).getall()
            
            # salary = " ".join(p.strip() for p in salary_parts if p.strip())
            
            # if not salary:
            #     salary = "Not disclosed"

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
            
            # --- Debug: if no salary found, dump the salary-related HTML ---
            if not salary:
                raw_salary_html = card.css(
                    "div[id='salaryInfoAndJobType'], "
                    "div[data-testid='jobsearch-OtherJobDetailsContainer'], "
                    "div[data-testid='attribute_snippet_text'], "
                    "div[data-testid='salary-snippet-container'], "
                    "span.css-1oc7tea"
                ).get()
            
                if raw_salary_html:
                    self.log(f"🧩 Salary HTML found but not parsed correctly: {raw_salary_html[:200]}...")
                else:
                    self.log("⚠️ No salary HTML detected in this job card snippet.")
            
            # --- Backup extraction ---
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

        # Pagination
        if self.api_calls < MAX_API_CALLS:
            next_page = response.css('a[aria-label="Next Page"]::attr(href), a[data-testid="pagination-page-next"]::attr(href)').get()
            if next_page:
                next_url = response.urljoin(next_page)
                yield from self.make_api_request(next_url, self.parse)

    def handle_error(self, failure):
        self.log(f"❌ Request failed: {failure.request.url}")

    def closed(self, reason):
        self.log(f"🧾 Total ScraperAPI calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
