import scrapy
from urllib.parse import urlencode
import os
import json
import re  # ✅ FIX: Added missing import for regex
from datetime import datetime, timedelta

API_KEY = os.getenv("SCRAPER_API_KEY", "your_fallback_api_key")
MAX_API_CALLS = 3  # Keep calls low, similar to Remote.co


def get_proxy_url(url):
    payload = {
        "api_key": API_KEY,
        "url": url,
        "country_code": "us",
        "render": "true",  # ✅ Rendering required for RemoteOK
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

    def start_requests(self):
        query = "React"
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

        # ✅ Debug HTML (helpful if 0 jobs found)
        with open("remoteok_debug.html", "wb") as f:
            f.write(response.body)

        # Select only real job rows
        job_rows = response.css("table#jobboard tr.job[data-id]")
        if not job_rows:
            self.log("⚠ No job rows found. Check remoteok_debug.html to inspect structure.")
            return

        self.log(f"✅ Found {len(job_rows)} job rows.")
        items_scraped = 0

        for row in job_rows[:30]:
            title = row.css("h2[itemprop='title']::text").get(default="").strip()
            company = row.css("h3[itemprop='name']::text").get(default="").strip()
            location = " ".join(row.css("div.location::text").getall()).strip() or "Remote"
            job_url = row.css("a.preventLink::attr(href)").get()
            if job_url and job_url.startswith("/"):
                job_url = f"https://remoteok.com{job_url}"

            # Tags & type
            tags = row.css("td.tags h3::text").getall()
            job_type = next((t for t in tags if any(k in t for k in ["Full-Time", "Part-Time", "Contract", "Freelance"])), "Not specified")
            salary = row.css("div.salary::text").get(default="Not disclosed").strip()

            # Date
            posted_text = row.css("time::text").get(default="").strip() or "N/A"

            # Skip duplicates
            if job_url in self.seen_urls:
                continue
            self.seen_urls.add(job_url)

            yield {
                "title": title,
                "company": company,
                "location": location,
                "salary": salary,
                "type": job_type,
                "posted": posted_text,
                "url": job_url,
            }
            items_scraped += 1

        self.log(f"📌 Jobs yielded from page: {items_scraped}")

    def handle_error(self, failure):
        req = getattr(failure, "request", None)
        url = req.url if req else "unknown"
        self.log(f"❌ Request failed: {url}")

    def closed(self, reason):
        self.log(f"🧾 Total API calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
