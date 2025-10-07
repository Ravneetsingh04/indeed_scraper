import scrapy
from urllib.parse import urlencode


import requests




# Replace with your API Key
API_KEY = '3ab10a9ef8e344f02041ab03db5b63ce'

def get_proxy_url(url):
    payload = { 'api_key': '3ab10a9ef8e344f02041ab03db5b63ce', 'url': 'https://httpbin.org/' }
    proxy_url = 'https://api.scraperapi.com/?' + urlencode(payload)
    return proxy_url

class IndeedSpider(scrapy.Spider):
    name = 'indeed'
    start_urls = ['https://www.indeed.com/']

    def start_requests(self):
        # Define your search parameters here
        search_query = 'software engineer'
        search_location = 'New York, NY'
        indeed_url = f'https://www.indeed.com/jobs?q={search_query}&l={search_location}'

        yield scrapy.Request(get_proxy_url(indeed_url), callback=self.parse)

    def parse(self, response):
        # Select all job cards from the search results page
        job_cards = response.css('.job_list_item')

        for card in job_cards:
            # Extract basic info
            title = card.css('.jobtitle ::text').get()
            company = card.css('.company ::text').get()
            location = card.css('.location ::text').get()
            job_url = card.css('a.jobtitle::attr(href)').get()
            full_job_url = response.urljoin(job_url)

            # Get job description from the detail page
            yield scrapy.Request(get_proxy_url(full_job_url), self.parse_details, meta={
                'title': title,
                'company': company,
                'location': location,
            })

        # Follow pagination link
        next_page = response.css('a[aria-label="Next Page"]::attr(href)').get()
        if next_page:
            next_page_url = response.urljoin(next_page)
            yield scrapy.Request(get_proxy_url(next_page_url), callback=self.parse)

    def parse_details(self, response):
        # Extract job description from the detail page
        description = response.css('#jobDescriptionText ::text').getall()
        description = " ".join(part.strip() for part in description if part.strip())

        yield {
            'title': response.meta['title'],
            'company': response.meta['company'],
            'location': response.meta['location'],
            'description': description,
            'url': response.url.split('url=')[1], # Get original URL
        }
