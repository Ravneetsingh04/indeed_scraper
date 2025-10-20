import scrapy
from urllib.parse import urlencode
import os
import json
from datetime import datetime, timedelta

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 3


def get_proxy_url(url):
    payload = {
        "api_key": API_KEY,
        "url": url,
        "country_code": "us",
        "render": "true",  # ✅ Rendering is needed once for initial page
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
        self.seen_urls = set()

    def start_requests(self):
        query = "Python"
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
        self.log(f"✅ Page {self.page_count} fetched successfully")

        # Save for debugging if empty
        with open("remoteok_debug.html", "wb") as f:
            f.write(response.body)

        # Extract the embedded JSON data (Next.js payload)
        json_data = response.css("script#__NEXT_DATA__::text").get()
        if not json_data:
            self.log("⚠ No __NEXT_DATA__ JSON found in HTML.")
            return

        try:
            data = json.loads(json_data)
            jobs = data.get("props", {}).get("pageProps", {}).get("jobs", [])
        except Exception as e:
            self.log(f"❌ Failed to parse JSON: {e}")
            return

        if not jobs:
            self.log("⚠ No jobs found inside Next.js data.")
            return

        self.log(f"✅ Found {len(jobs)} jobs in JSON payload.")
        items_scraped = 0

        for job in jobs:
            job_url = f"https://remoteok.com{job.get('url', '')}"
            if job_url in self.seen_urls:
                continue
            self.seen_urls.add(job_url)

            title = job.get("position", "").strip()
            company = job.get("company", "").strip()
            location = job.get("location", "Remote").strip()
            salary = job.get("salary", "Not disclosed")
            job_type = job.get("tags", [])
            job_type = next((t for t in job_type if t in ["Full-Time", "Part-Time", "Contract", "Freelance"]), "Not specified")
            posted = job.get("date", "") or job.get("epoch", "")

            yield {
                "title": title,
                "company": company,
                "location": location,
                "salary": salary,
                "type": job_type,
                "posted": posted,
                "url": job_url,
            }
            items_scraped += 1

        self.log(f"📌 Jobs yielded: {items_scraped}")

    def handle_error(self, failure):
        req = getattr(failure, "request", None)
        url = req.url if req else "unknown"
        self.log(f"❌ Request failed: {url}")

    def closed(self, reason):
        self.log(f"🧾 Total API calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
