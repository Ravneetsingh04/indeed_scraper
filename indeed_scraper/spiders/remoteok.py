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
        "render": "true",  #Rednering true for now
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
        query = "React"
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

        # Save a debug copy
        with open("remoteok_debug.html", "wb") as f:
            f.write(response.body)

        # ✅ Use JSON blocks instead of visible HTML rows
        json_blocks = re.findall(
            r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
            response.text,
            re.DOTALL,
        )

        if not json_blocks:
            self.log("⚠ No JSON job blocks found. Dumping HTML for inspection.")
            with open("remoteok_debug.html", "wb") as f:
                f.write(response.body)
            return

        self.log(f"✅ Found {len(json_blocks)} job JSON blocks.")
        items_scraped = 0

        for block in json_blocks:
            try:
                data = json.loads(block)
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
                desc = (data.get("description") or "").replace("\n", " ").strip()[:300]

                # Skip invalid or duplicate jobs
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
                    "url": job_url or response.url,
                    "description": desc,
                }
                items_scraped += 1

            except json.JSONDecodeError:
                continue

        self.log(f"📌 Jobs yielded from page: {items_scraped}")
    def handle_error(self, failure):
        req = getattr(failure, "request", None)
        url = req.url if req is not None else "unknown"
        self.log(f"❌ Request failed: {url}")

    def closed(self, reason):
        self.log(f"🧾 Total API calls made: {self.api_calls}/{MAX_API_CALLS}")
        self.log(f"📊 Total unique jobs scraped: {len(self.seen_urls)}")
