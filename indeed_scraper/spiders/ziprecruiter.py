import scrapy
from urllib.parse import quote_plus
from datetime import datetime


class ZipRecruiterSpider(scrapy.Spider):
    name = "ziprecruiter"

    # We bypass robots.txt here because ZR disallows bots; otherwise Scrapy will skip the page.
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DEFAULT_REQUEST_HEADERS": {
            # A realistic desktop UA helps reduce soft-blocks
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # allow -a query="..." -a location="..."
        self.query = kwargs.get("query", "AI Developer")
        self.location = kwargs.get("location", "New York, NY")
        self.seen_urls = set()

    def start_requests(self):
        q = quote_plus(self.query)
        loc = quote_plus(self.location)
        url = f"https://www.ziprecruiter.com/candidate/search?search={q}&location={loc}"
        self.logger.info(f"🌐 Fetching first page only: {url}")
        yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        if response.status != 200:
            self.logger.warning(f"Non-200 status {response.status} for {response.url}")
            return

        # Try multiple card patterns for resilience
        cards = response.css(
            "article.job_result, div.job_result, div.job_content, div[data-testid='job_card']"
        )
        self.logger.info(f"Found {len(cards)} potential job cards on the first page.")

        today = datetime.now().strftime("%Y-%m-%d")

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

            # Posted date (ZR often shows 'X days ago'; we record scrape date for stability)
            posted = today

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

        # First page only → no pagination
        self.logger.info(
            f"✅ First page scraped. Unique jobs yielded: {len(self.seen_urls)}"
        )
