import scrapy
from urllib.parse import quote_plus
from datetime import datetime


class ZipRecruiterSpider(scrapy.Spider):
    name = "ziprecruiter"

    # accept 403 so we can handle it in parse()
    handle_httpstatus_list = [403]

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "FEED_EXPORT_ENCODING": "utf-8",
    }

    # Primary desktop-like header (first attempt)
    desktop_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        # Browser-ish fetch metadata
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
    }

    # Alternate mobile-like header (retry attempt)
    mobile_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Mobile Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.ziprecruiter.com/",
        "Origin": "https://www.ziprecruiter.com",
        "Sec-Ch-Ua": '"Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query = kwargs.get("query", "AI Developer")
        self.location = kwargs.get("location", "New York, NY")
        self.seen_urls = set()
        self.today = datetime.now().strftime("%Y-%m-%d")

    def start_requests(self):
        q = quote_plus(self.query)
        loc = quote_plus(self.location)
        url = f"https://www.ziprecruiter.com/candidate/search?search={q}&location={loc}"
        self.logger.info(f"🌐 Starting fetch (first page only): {url}")
        # initial request uses desktop headers and marks as not retried
        yield scrapy.Request(
            url,
            callback=self.parse,
            headers=self.desktop_headers,
            dont_filter=True,
            meta={"retried": False},
        )

    def parse(self, response):
        status = response.status
        url = response.url
        retried = response.meta.get("retried", False)

        if status == 403:
            # try one retry with mobile/stealth headers
            if not retried:
                self.logger.warning(f"403 Forbidden received for {url} — retrying once with stealth headers.")
                yield scrapy.Request(
                    url,
                    callback=self.parse,
                    headers=self.mobile_headers,
                    dont_filter=True,
                    meta={"retried": True},
                )
                return
            else:
                self.logger.error(f"403 Forbidden again for {url} after retry — aborting scrape for this run.")
                return

        if status != 200:
            self.logger.warning(f"Non-200 status {status} for {url} — aborting.")
            return

        # Try multiple card patterns for resilience
        cards = response.css(
            "article.job_result, div.job_result, div.job_content, div[data-testid='job_card']"
        )
        self.logger.info(f"Found {len(cards)} potential job cards on the first page.")

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
            salary = " ".join(p.strip() for p in salary_parts if p.strip())
            if not salary:
                salary = card.xpath(
                    ".//*[contains(., '$') or contains(., 'hour') or contains(., 'year') or contains(., 'month')]/text()"
                ).get(default="").strip() or "Not disclosed"

            # Posted date (we record scrape date for stability)
            posted = self.today

            # Job URL
            href = (
                card.css("a.job_link::attr(href)").get()
                or card.css("a[data-testid='job_link']::attr(href)").get()
                or card.css("a::attr(href)").get()
            )
            if not href:
                continue

            job_url = response.urljoin(href)

            # De-dupe
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

        self.logger.info(f"✅ First page scraped. Unique jobs yielded: {len(self.seen_urls)}")
