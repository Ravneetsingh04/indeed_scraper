import os
import random
from datetime import datetime
from urllib.parse import urlencode, quote_plus

import scrapy

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
MAX_API_CALLS = 5               # hard cap for API calls
MAX_RETRIES_PER_URL = 3         # rotate UA & retry for 403/5xx once or twice

# A small pool of realistic UAs (desktop + mobile) to rotate
UA_POOL = [
    # Desktop Chrome variants
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # Mobile Chrome variants
    "Mozilla/5.0 (Linux; Android 14; Pixel 7 Pro) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]

def proxy_url(target_url: str, user_agent: str) -> str:
    """Build ScraperAPI URL with JS rendering and UA forwarding."""
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": target_url,
        "render": "true",          # JS rendering to bypass bot wall
        "country_code": "us",      # ZipRecruiter US pages
        # keep_headers=true makes ScraperAPI forward our UA
        "keep_headers": "true",
    }
    # Some providers honor 'device_type=mobile/desktop'; ScraperAPI ignores it safely.
    if "Mobile" in user_agent or "iPhone" in user_agent or "Android" in user_agent:
        params["device_type"] = "mobile"
    else:
        params["device_type"] = "desktop"
    return "https://api.scraperapi.com/?" + urlencode(params)


class ZipRecruiterSpider(scrapy.Spider):
    name = "ziprecruiter"
    # Accept 403/500 so we can handle smart retries
    handle_httpstatus_list = [403, 429, 500, 502, 503, 504]

    custom_settings = {
        "ROBOTSTXT_OBEY": False,              # we’re proxy-rendering; robots.txt would block
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "FEED_EXPORT_ENCODING": "utf-8",
        "DEFAULT_REQUEST_HEADERS": {
            # ScraperAPI uses our headers if keep_headers=true
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.google.com/",
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not SCRAPER_API_KEY:
            raise RuntimeError("SCRAPER_API_KEY is not set in the environment/secrets.")

        self.query = kwargs.get("query", "AI Developer")
        self.location = kwargs.get("location", "New York, NY")
        self.today = datetime.now().strftime("%Y-%m-%d")
        self.api_calls = 0
        self.seen_urls = set()

    # First page only
    def start_requests(self):
        q = quote_plus(self.query)
        loc = quote_plus(self.location)
        zr_url = f"https://www.ziprecruiter.com/candidate/search?search={q}&location={loc}"

        ua = random.choice(UA_POOL)
        url = proxy_url(zr_url, ua)
        self.api_calls += 1
        self.logger.info(f"📡 ScraperAPI call #{self.api_calls}/{MAX_API_CALLS}: {zr_url} (render=true)")

        yield scrapy.Request(
            url,
            callback=self.parse_search,
            headers={"User-Agent": ua},
            meta={
                "orig_url": zr_url,
                "retry_count": 0,
                "ua": ua,
            },
            dont_filter=True,
        )

    def parse_search(self, response):
        with open("debug_zip.html", "w", encoding="utf-8") as f:
        f.write(response.text)
        status = response.status
        orig_url = response.meta.get("orig_url")
        retry_count = response.meta.get("retry_count", 0)
        current_ua = response.meta.get("ua", UA_POOL[0])

        if status != 200:
            # Retry if allowed, vary UA
            if retry_count < MAX_RETRIES_PER_URL and self.api_calls < MAX_API_CALLS:
                new_ua = random.choice([ua for ua in UA_POOL if ua != current_ua] or UA_POOL)
                proxied = proxy_url(orig_url, new_ua)
                self.api_calls += 1
                self.logger.warning(
                    f"🔁 Status {status} on {orig_url}. Retrying {retry_count+1}/{MAX_RETRIES_PER_URL} "
                    f"with rotated UA via ScraperAPI (call {self.api_calls}/{MAX_API_CALLS})."
                )
                yield scrapy.Request(
                    proxied,
                    callback=self.parse_search,
                    headers={"User-Agent": new_ua},
                    meta={"orig_url": orig_url, "retry_count": retry_count + 1, "ua": new_ua},
                    dont_filter=True,
                )
                return

            self.logger.error(f"❌ Gave up after status {status} for {orig_url}.")
            return

        # From here we have rendered HTML. Try robust selectors.
        cards = response.css(
            "article.job_result, div.job_result, div.job_content, div[data-testid='job_card']"
        )
        self.logger.info(f"✅ Rendered page OK. Found {len(cards)} potential job cards.")

        if not cards:
            # Sometimes listings are inside script tags rendered by client; ScraperAPI render=true should handle it.
            self.logger.warning("⚠ No job cards detected. The HTML structure may have changed.")
            return

        for card in cards:
            # Title
            title = (
                card.css("a.job_link::text").get()
                or card.css("a[data-testid='job_link']::text").get()
                or card.css("a::text").get()
            )
            title = (title or "").strip()

            # Company
            company = (
                card.css("a.t_org_link::text").get()
                or card.css("div.job_org::text").get()
                or card.css("[data-testid='job-card-company-name']::text").get()
                or card.css("span.company_name::text").get()
            )
            company = (company or "").strip()

            # Location
            loc_parts = card.css(
                "span.job_location::text, div.job_location::text, [data-testid='job-card-location'] *::text"
            ).getall()
            location = " ".join(p.strip() for p in loc_parts if p.strip())

            # Salary (best-effort)
            salary_parts = card.css(
                "span.job_salary::text, div.job_salary::text, [data-testid='job-card-salary'] *::text"
            ).getall()
            salary = " ".join(p.strip() for p in salary_parts if p.strip()) or ""
            if not salary:
                salary = card.xpath(
                    ".//*[contains(., '$') or contains(., 'hour') or contains(., 'year') or contains(., 'month')]/text()"
                ).get(default="").strip() or "Not disclosed"

            posted = self.today

            # Job link
            href = (
                card.css("a.job_link::attr(href)").get()
                or card.css("a[data-testid='job_link']::attr(href)").get()
                or card.css("a::attr(href)").get()
            )
            if not href:
                continue
            job_url = response.urljoin(href)

            if job_url in self.seen_urls:
                continue
            self.seen_urls.add(job_url)

            yield {
                "title": title,
                "company": company,
                "location": location,
                "salary": salary,
                "posted": posted,
                "url": job_url,
            }

        self.logger.info(
            f"🧾 Total ScraperAPI calls used: {self.api_calls}/{MAX_API_CALLS} | "
            f"📊 Unique jobs yielded: {len(self.seen_urls)}"
        )
        # First page only: stop here.
