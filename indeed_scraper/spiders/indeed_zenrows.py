import scrapy
from urllib.parse import urlencode, urljoin, quote
import os
from datetime import datetime
import inspect

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml"
}
SESSION_ID = "indeed_scrape_session_1"
ZENROWS_KEY = os.getenv("ZENROWS_API_KEY", "your_fallback_zenrows_key")
MAX_API_CALLS = 5


def get_proxy_url(url):
   
    # --- Encode custom headers safely ---
    import json
    import urllib.parse

    headers_json = json.dumps({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    })
    encoded_headers = urllib.parse.quote(headers_json)

    payload = {
        "apikey": ZENROWS_KEY,
        "url": quote(url, safe=":/?&="),
        "js_render": "true",             # ✅ render JS for Indeed
        "antibot": "true",
        "premium_proxy": "true",
        "wait_until": "networkidle",
        "custom_headers": encoded_headers  # ✅ safely encoded
    }

    # ✅ Join manually to avoid double encoding issues
    return "https://api.zenrows.com/v1/?" + "&".join(f"{k}={v}" for k, v in payload.items())


class IndeedZenRowsSpider(scrapy.Spider):
    name = "indeed_zenrows"

    custom_settings = {
        "RETRY_ENABLED": False,
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "CLOSESPIDER_PAGECOUNT": 5,
        "REDIRECT_ENABLED": False, # <-- ➕ NEW: Explicitly disable redirect middleware
        "HTTPERROR_ALLOWED_CODES": [403, 503, 404, 301, 302],
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pageCount = 0
        self.api_calls = 0
        self.seen_urls = set()
        self.visited_pages = set()

    def start_requests(self):
        # keep dynamic fields the same as your current spider
        search_query = getattr(self, "search_query", "Python Developer")
        search_location = getattr(self, "search_location", "New York, NY")
        self.log(f"🔑 ZenRows Key Loaded: {os.getenv('ZENROWS_API_KEY')[:6]}***")


        # NOTE: we're keeping the desktop endpoint here so your current parse code works unchanged
        # You can switch to /m/jobs later for mobile version testing (see notes).
        indeed_url = f"https://www.indeed.com/jobs?q={search_query}&l={search_location}&fromage=1"
        yield from self.make_api_request(indeed_url, self.parse)

    def make_api_request(self, url, callback, **kwargs):
        if self.api_calls >= MAX_API_CALLS:
            self.log(f"⛔ API limit reached ({self.api_calls}/{MAX_API_CALLS}). Stopping crawl.")
            return

        self.api_calls += 1
        self.log(f"📡 ZENROWS API Call #{self.api_calls}: {url}")
        stack = [f"{frame.function}()" for frame in inspect.stack()[1:4]]
        self.log(f"🧭 Call triggered from: {' → '.join(stack)}")

        yield scrapy.Request(
            get_proxy_url(url),
            callback=callback,
            errback=self.handle_error,
            headers=headers,
            dont_filter=True,
            meta={"dont_redirect": True,},
            **kwargs,
        )

    # ---- keep your exact parse() implementation as-is so HTML parsing is unchanged ----
    def parse(self, response):
        if response.status != 200:
            self.log(f"⚠️ ZenRows returned status {response.status} — body snippet: {response.text[:300]}")
            return
        self.pageCount += 1
        if self.api_calls > 1:
            self.log("⛔ Preventing further requests (single-call mode enforced)")
            return

        self.log(f"--- Fetched page {self.pageCount}: {response.url} (status {response.status})")

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
            location_parts = card.css("div.companyLocation *::text, div[data-testid='text-location'] *::text").getall()
            location = " ".join(p.strip() for p in location_parts if p.strip())

            salary_parts = card.css(
                "div[id='salaryInfoAndJobType'] span::text, "
                "div[data-testid='attribute_snippet_text']::text, "
                "div[data-testid='jobsearch-OtherJobDetailsContainer'] span::text, "
                "div[data-testid='salary-snippet-container'] span::text, "
                "span.css-1oc7tea::text, "
                "span[data-testid='attribute_snippet_text']::text"
            ).getall()
            salary = " ".join(p.strip() for p in salary_parts if p.strip())
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
                job_url = urljoin("https://www.indeed.com", job_url)

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

        self.log(f"📌 Items yielded from page: {len(self.seen_urls)}")
        self.log("✅ Completed single batch scrape (no further pagination).")

    def handle_error(self, failure):
        req = getattr(failure, "request", None)
        url = req.url if req is not None else "unknown"
        self.log(f"❌ Request failed: {url}")

    def closed(self, reason):
        self.log(f"🧾 Total ZenRows calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
