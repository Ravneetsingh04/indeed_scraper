import scrapy
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from indeed_scraper.utils.selenium_driver import get_driver


class IndeedSeleniumSpider(scrapy.Spider):
    name = "indeed_selenium"

    def start_requests(self):
        search_query = "Python Developer"
        search_location = "New York, NY"
        indeed_url = f"https://www.indeed.com/jobs?q={search_query}&l={search_location}&fromage=1"

        self.log(f"🌐 Fetching jobs with Selenium: {indeed_url}")
        driver = get_driver()
        driver.get(indeed_url)
        driver.implicitly_wait(5)

        html = driver.page_source
        driver.quit()

        yield from self.parse_html(html, indeed_url)

    def parse_html(self, html, url):
        soup = BeautifulSoup(html, "html.parser")
        job_cards = soup.select("div.job_seen_beacon, a.tapItem")

        if not job_cards:
            self.log("⚠ No job cards found.")
            return

        self.log(f"✅ Found {len(job_cards)} job cards.")

        seen_urls = set()
        for card in job_cards[:10]:
            title_tag = card.select_one("h2.jobTitle span, h2 span, a[aria-label]")
            title = title_tag.get_text(strip=True) if title_tag else None

            company_tag = card.select_one("span.companyName, span[data-testid='company-name']")
            company = company_tag.get_text(strip=True) if company_tag else None

            location_parts = [p.get_text(strip=True) for p in card.select("div.companyLocation *, div[data-testid='text-location'] *")]
            location = " ".join(location_parts)

            salary_parts = [p.get_text(strip=True) for p in card.select(
                "div[id='salaryInfoAndJobType'] span, "
                "div[data-testid='attribute_snippet_text'], "
                "div[data-testid='jobsearch-OtherJobDetailsContainer'] span, "
                "div[data-testid='salary-snippet-container'] span, "
                "span.css-1oc7tea, "
                "span[data-testid='attribute_snippet_text']"
            )]

            salary = " ".join(salary_parts).strip() or "Not disclosed"
            posted = datetime.now().strftime("%Y-%m-%d")

            job_url_tag = card.select_one("a[href]")
            if not job_url_tag:
                continue

            job_url = job_url_tag["href"]
            if job_url.startswith("/pagead/clk"):
                continue
            elif job_url.startswith("/"):
                job_url = urljoin("https://www.indeed.com", job_url)

            if job_url in seen_urls:
                continue

            seen_urls.add(job_url)

            yield {
                "title": title or "",
                "company": company or "",
                "location": location or "",
                "salary": salary or "",
                "posted": posted,
                "url": job_url,
            }

        self.log(f"📌 Items yielded: {len(seen_urls)}")
