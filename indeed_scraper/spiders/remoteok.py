import scrapy
from urllib.parse import urlencode
import os
import json
import re  # ✅ FIX: Added missing import for regex
from datetime import datetime, timedelta, timezone

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
        # ✅ Define 24-hour cutoff timestamp
        self.cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)

    def start_requests(self):
        query = "Java"
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

        # ✅ Debug dump (helpful if 0 jobs found)
        with open("remoteok_debug.html", "wb") as f:
            f.write(response.body)

        # ✅ Extract embedded job data JSON blocks
        json_blocks = re.findall(
            r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
            response.text,
            re.DOTALL,
        )

        if not json_blocks:
            self.log("⚠ No JSON job blocks found — check remoteok_debug.html for actual HTML.")
            return

        self.log(f"✅ Found {len(json_blocks)} JSON job entries")
        items_scraped = 0

        for block in json_blocks:
            try:
                data = json.loads(block)
                date_posted = data.get("datePosted")

                # ✅ Skip if no date
                if not date_posted:
                    continue

                try:
                    posted_time = datetime.fromisoformat(date_posted.replace("Z", "+00:00"))
                except ValueError:
                    continue

                # ✅ Apply 24-hour filter
                if posted_time < self.cutoff_time:
                    continue
                title = (data.get("title") or "").strip()
                company = (data.get("hiringOrganization", {}).get("name") or "").strip()
                location = (
                    data.get("jobLocation", [{}])[0]
                    .get("address", {})
                    .get("addressCountry", "Remote")
                )
                job_url = data.get("hiringOrganization", {}).get("url") or ""
                salary_info = data.get("baseSalary", {}).get("value", {})
                min_salary = salary_info.get("minValue")
                max_salary = salary_info.get("maxValue")
                currency = data.get("baseSalary", {}).get("currency", "")

                if not title or not company:
                    continue
                if job_url in self.seen_urls:
                    continue
                self.seen_urls.add(job_url)

                yield {
                    "title": title,
                    "company": company,
                    "location": location,
                    "salary_range": (
                        f"{min_salary}-{max_salary} {currency}"
                        if min_salary
                        else "Not specified"
                    ),
                    "posted": posted_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "url": job_url or response.url,
                }
                items_scraped += 1

            except json.JSONDecodeError:
                continue

        self.log(f"📌 Jobs yielded from page: {items_scraped}")

    def handle_error(self, failure):
        req = getattr(failure, "request", None)
        url = req.url if req else "unknown"
        self.log(f"❌ Request failed: {url}")

    def closed(self, reason):
        self.log(f"🧾 Total API calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
