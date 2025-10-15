import os
from urllib.parse import urlencode

SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", "your_fallback_key")

def get_scrapingbee_url(target_url: str, render_js: bool = False, premium_proxy: bool = False,
                       wait: int | None = None, country: str | None = None) -> str:
    params = {"api_key": SCRAPINGBEE_API_KEY, "url": target_url}
    if render_js:
        params["render_js"] = "true"
    if premium_proxy:
        params["premium_proxy"] = "true"
    if wait is not None:
        params["wait"] = str(int(wait))
    if country:
        params["country_code"] = country
    return "https://app.scrapingbee.com/api/v1/?" + urlencode(params)
