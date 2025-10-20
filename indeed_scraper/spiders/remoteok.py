import scrapy
from urllib.parse import urlencode, urljoin
import os
from datetime import datetime, timedelta

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 3  # Keep calls low, similar to Remote.co


def get_proxy_url(url):
    payload = {
        "api_key": API_KEY,
        "url": url,
        "country_code": "us",
        "render": "false",  # ✅ RemoteOK is static HTML
        "premium": "false",
        "num_retries": 1,
        "cache": "true",
    }
    return "https://api.scraperapi.com/?" + urlencode(payload)


class RemoteOKSpider(scrapy.Spider):
    name = "remoteok"

    custom_settings = {
        "RETRY_ENABLED": False,
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "CLOSESPIDER_PAGECOUNT": 3,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_calls = 0
        self.page_count = 0
        self.visited_pages = set()
        self.seen_urls = set()
        self.cutoff_date = datetime.utcnow() - timedelta(days=1)  # ✅ 24-hour filter window

    def start_requests(self):
        query = "salesforce developer"
        # RemoteOK search URL pattern
        start_url = f"https://remoteok.com/remote-{query.replace(' ', '-')}-jobs"
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
        self.log(f"✅ Fetched page {self.page_count}: {response.url} (status {response.status})")

        # ✅ RemoteOK job cards live inside a table with class="jobsboard"
        job_cards = response.css("tr.job")  # each job listing is in a <tr class='job'>

        if not job_cards:
            self.log("⚠ No job cards found — check structure or blocking")
            return
        else:
            self.log(f"✅ Found {len(job_cards)} job cards.")

        items_scraped = 0
        for card in job_cards[:30]:
            title = card.css("td.position h2::text").get()
            company = card.css("td.company h3::text").get()
            location = card.css("div.location::text").get()
            posted = card.css("time::attr(datetime)").get()
            job_url = card.css("a.preventLink::attr(href)").get()

            if not job_url:
                continue

            # ✅ Ensure full accessible RemoteOK URL
            if job_url.startswith("/"):
                job_url = f"https://remoteok.com{job_url}"
            elif not job_url.startswith("http"):
                job_url = f"https://remoteok.com/{job_url}"

            # Job type and salary (optional)
            tags = card.css("div.tags a::text").getall()
            job_type = next((t for t in tags if any(k in t for k in ["Full-Time", "Part-Time", "Contract", "Freelance"])), "Not specified")
            salary = next((t for t in tags if "$" in t), "Not disclosed")

            # ✅ Filter by last 24 hours
            include_job = False
            posted_text = (posted or "").strip().lower()

            if any(k in posted_text for k in ["hour", "today", "just posted", "minutes ago"]):
                include_job = True
            else:
                try:
                    posted_date = datetime.strptime(posted_text.split("T")[0], "%Y-%m-%d")
                    if posted_date >= self.cutoff_date:
                        include_job = True
                except Exception:
                    include_job = False

            if not include_job:
                continue  # Skip older listings

            if job_url in self.seen_urls:
                continue
            self.seen_urls.add(job_url)

            yield {
                "title": (title or "").strip(),
                "company": (company or "RemoteOK Listing").strip(),
                "location": (location or "Not specified").strip(),
                "posted": posted or datetime.now().strftime("%Y-%m-%d"),
                "type": job_type.strip(),
                "url": job_url,
            }
            items_scraped += 1

        self.log(f"📌 Items yielded from page: {items_scraped}")

        # ✅ RemoteOK doesn't have traditional pagination — stop after first page
        self.log("ℹ️ RemoteOK listings fetched (no pagination).")

    def handle_error(self, failure):
        req = getattr(failure, "request", None)
        url = req.url if req is not None else "unknown"
        self.log(f"❌ Request failed: {url}")

    def closed(self, reason):
        self.log(f"🧾 Total API calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
