import scrapy
from urllib.parse import urlencode, urljoin
import os
from datetime import datetime
import inspect

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml"
}


API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 5


def get_proxy_url(url):
    # PROXY URL BUILDER (Removed render=true)
    payload = {
                "api_key": API_KEY,
                "url": url,
                "country_code": "us", #Reduce proxy rotation 
                "render": "false",    #Explicitly disable rendering
                "premium": "false",   #Avoid expensive “premium” geo hops
                "num_retries": 0,     #Limit backend retries
                "cache": "true",       #Cache static pages
                "block_ads": "true",         # 🚫 new: block ads and analytics
                "block_resources": "true",   # 🚫 new: block images, css, scripts
                "follow_redirect": "false",   # 🚫 stop following redirects (saves credits)
                "keep_headers": "true",       # ensure headers aren’t re-fetched
              }
    return "https://api.scraperapi.com/?" + urlencode(payload)


class IndeedSpider(scrapy.Spider):
    name = "indeed"

    # CUSTOM SCRAPY SETTINGS (Disable retries & robots.txt)
    
    custom_settings = {
        "RETRY_ENABLED": False,          # avoid retrying failed ScraperAPI calls
        "ROBOTSTXT_OBEY": False,         # don't waste calls checking robots.txt
        "DOWNLOAD_DELAY": 1,             # polite delay between requests
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "CLOSESPIDER_PAGECOUNT": 5       # safety stop during testing
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pageCount = 0
        self.api_calls = 0
        self.seen_urls = set()
        self.visited_pages = set()  # Added to prevent duplicate pagination calls

    def start_requests(self):
        search_query = "Python Developer"
        search_location = "New York, NY"
        #Added 24 hrs filter
        indeed_url = f"https://www.indeed.com/jobs?q={search_query}&l={search_location}&fromage=1"
        yield from self.make_api_request(indeed_url, self.parse_mobile)

    def make_api_request(self, url, callback, **kwargs):
        if self.api_calls >= MAX_API_CALLS:
            self.log(f"⛔ API limit reached ({self.api_calls}/{MAX_API_CALLS}). Stopping crawl.")
            return

        self.api_calls += 1
        self.log(f"📡 API Call #{self.api_calls}: {url}")
        # this will show which function triggered each call
        stack = [f"{frame.function}()" for frame in inspect.stack()[1:4]]
        self.log(f"🧭 Call triggered from: {' → '.join(stack)}")

        yield scrapy.Request(
            get_proxy_url(url),
            callback=callback,
            errback=self.handle_error,
            headers=headers,
            dont_filter=True,                   # avoid duplicate filtering
            meta={"dont_redirect": True,
                  "handle_httpstatus_list": [301, 302, 303, 307, 308]
                 },       # disable redirects (each costs credits)
            **kwargs,
        )

    def parse(self, response):
        self.pageCount += 1
        if self.api_calls > 1:
            self.log("⛔ Preventing further requests (single-call mode enforced)")
            return

        
        self.log(f"--- Fetched page {self.pageCount}: {response.url} (status {response.status})")

        # Use both div.job_seen_beacon and attribute fallbacks for reliability
        job_cards = response.css('div.job_seen_beacon, a.tapItem')

        if not job_cards:
            self.log("⚠ No job cards found — check HTML structure.")
            return
        else:
            self.log(f"✅ Found {len(job_cards)} job cards.")

        for card in job_cards[:5]:
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

            if job_url.startswith("/pagead/clk"):
                self.log(f"⛔ Skipping ad URL: {job_url}")
                continue
            elif job_url.startswith("/"):
                job_url = urljoin("https://www.indeed.com",job_url)

            if job_url in self.seen_urls:
                continue
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

        # Pagination
        # if self.api_calls < MAX_API_CALLS:
        #     next_page = response.css('a[aria-label="Next Page"]::attr(href), a[data-testid="pagination-page-next"]::attr(href)').get()
        #     if next_page:
        #         # Always join against Indeed’s domain — not ScraperAPI’s
        #         next_url = urljoin("https://www.indeed.com", next_page)

        #         # ✅ Prevent duplicate or recursive pagination
        #         if next_url not in self.visited_pages:
        #             self.visited_pages.add(next_url)
        #             yield from self.make_api_request(next_url, self.parse)
        #         else:
        #             self.log(f"🔁 Skipping duplicate page: {next_url}")
    
        self.log(f"📌 Items yielded from page: {len(self.seen_urls)}")

        # ⚡ No pagination calls — single API hit behavior (like WWR)
        self.log("✅ Completed single batch scrape (no further pagination).")


    def parse_mobile(self, response):
        """Lighter version of parse() for Indeed’s mobile endpoint (/m/jobs)."""
        self.pageCount += 1
        self.log(f"--- Fetched MOBILE page {self.pageCount}: {response.url} (status {response.status})")
    
        # The mobile site has a simpler structure: div.job containers
        job_cards = response.css("div.job")
    
        if not job_cards:
            self.log("⚠ No job cards found on mobile site.")
            return
        else:
            self.log(f"✅ Found {len(job_cards)} mobile job cards.")
    
        for card in job_cards[:10]:
            title = card.css("a.jobtitle::text").get()
            company = card.css("div.company::text").get()
            location = card.css("div.location::text").get()
            salary = card.css("span.salary::text, div.salarySnippet::text").get(default="Not disclosed")
    
            job_url = card.css("a.jobtitle::attr(href)").get()
            if job_url and job_url.startswith("/"):
                job_url = f"https://www.indeed.com{job_url}"
    
            if not job_url or job_url in self.seen_urls:
                continue
    
            self.seen_urls.add(job_url)
    
            yield {
                "title": (title or "").strip(),
                "company": (company or "").strip(),
                "location": (location or "").strip(),
                "salary": (salary or "").strip(),
                "posted": datetime.now().strftime("%Y-%m-%d"),
                "url": job_url,
            }

        self.log(f"📌 Items yielded from MOBILE page: {len(self.seen_urls)}")
        self.log("✅ Completed single mobile batch scrape (no further pagination).")


    def handle_error(self, failure):
        self.log(f"❌ Request failed: {failure.request.url}")

    def closed(self, reason):
        self.log(f"🧾 Total ScraperAPI calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
