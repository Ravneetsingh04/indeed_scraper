import scrapy
from urllib.parse import urlencode, urljoin
import os
from datetime import datetime, timedelta

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 3  # Remote.co is light, so a few API calls max


def get_proxy_url(url):
    payload = {
        "api_key": API_KEY,
        "url": url,
        "country_code": "us",
        "render": "true",
        "premium": "false",
        "num_retries": 1,
        "cache": "true",
    }
    return "https://api.scraperapi.com/?" + urlencode(payload)


class RemoteCoSpider(scrapy.Spider):
    name = "remote_co"

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
        self.cutoff_date = datetime.utcnow() - timedelta(days=1)  # ✅ Only jobs <= 24h old

    def start_requests(self):
        query = "salesforce developer"
        start_url = f"https://remote.co/remote-jobs/search/?search_keywords={query.replace(' ', '+')}"
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

        job_cards = response.css("div#job-table-wrapper div.sc-hxaYUE.knZTmB")  # Remote.co uses div.card for job entries

        if not job_cards:
            self.log("⚠ No job cards found — check HTML structure or blocking")
            return
        else:
            self.log(f"✅ Found {len(job_cards)} job cards.")

        items_scraped = 0
        for card in job_cards[:30]:
            title = card.css("a.sc-lcUlUk span.sc-fLdTid.hxOunA::text").get()
            posted = card.css("a.sc-lcUlUk span.sc-kQZgv.gVdgMf::text").get()
            job_url = card.css("a.sc-lcUlUk::attr(href)").get()
            if not job_url:
                continue
            
            # ✅ Fix: Always build full URL using remote.co, not response.urljoin()
            if job_url.startswith("/"):
                job_url = f"https://remote.co{job_url}"
            elif not job_url.startswith("http"):
                job_url = f"https://remote.co/{job_url}"

            tags = card.css("ul.sc-bBUFSZ.kSPuZK li::text").getall()
            location = card.css("div.sc-fPcgZv.fSjLPq span.sc-kXbFWK.jgBZbs::text").get()

            # Basic tag filtering
            job_type = next((t for t in tags if "Full-Time" in t or "Part-Time" in t or "Freelance" in t or "Contract" in t), "Not specified")
            salary = next((t for t in tags if "$" in t or "Annually" in t or "Hourly" in t), "Not disclosed")
            company = "Remote.co Listing"  # or set to "Not specified"
            # ✅ 24-hour filter logic
            posted_text = (posted or "").strip().lower()
            include_job = False

            if any(k in posted_text for k in ["hour", "today", "just posted", "minutes ago"]):
                include_job = True
            elif "day" in posted_text:
                try:
                    days_ago = int([s for s in posted_text.split() if s.isdigit()][0])
                    if days_ago <= 1:
                        include_job = True
                except Exception:
                    pass
            else:
                # fallback: if it's a date, check if within 24 hours
                try:
                    posted_date = datetime.strptime(posted_text, "%Y-%m-%d")
                    include_job = posted_date >= self.cutoff_date
                except Exception:
                    include_job = False

            if not include_job:
                continue  # Skip anything older than 24 hours

            if not job_url or job_url in self.seen_urls:
                continue
            self.seen_urls.add(job_url)

            yield {
                "title": (title or "").strip(),
                "company": (company or "").strip(),
                "location": (location or "").strip(),
                "posted": posted.strip(),
                "type": job_type.strip(),
                "url": job_url,
            }
            items_scraped += 1

        self.log(f"📌 Items yielded from page: {items_scraped}")

        # Pagination
        next_page = response.css("a.next.page-numbers::attr(href)").get()
        if next_page and self.api_calls < MAX_API_CALLS:
            next_url = urljoin("https://remote.co", next_page)
            if next_url not in self.visited_pages:
                self.visited_pages.add(next_url)
                yield from self.make_api_request(next_url, self.parse)

    def handle_error(self, failure):
        req = getattr(failure, "request", None)
        url = req.url if req is not None else "unknown"
        self.log(f"❌ Request failed: {url}")

    def closed(self, reason):
        self.log(f"🧾 Total API calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
