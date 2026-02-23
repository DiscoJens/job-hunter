from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from urllib.parse import urlencode
from bs4 import BeautifulSoup
import asyncio
import httpx
import time
import json
import base64

_filters_cache = None


def _make_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.binary_location = "/usr/bin/chromium-browser"
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(service=Service("/usr/bin/chromedriver"), options=options)


def _get_page_data(driver: webdriver.Chrome, url: str) -> dict:
    driver.get(url)
    time.sleep(3)
    scripts = driver.find_elements(By.TAG_NAME, "script")
    big = max(scripts, key=lambda s: len(s.get_attribute("innerHTML") or ""))
    raw = big.get_attribute("innerHTML").strip()
    return json.loads(base64.b64decode(raw).decode("utf-8"))


def get_filters() -> dict:
    global _filters_cache
    if _filters_cache is not None:
        return _filters_cache

    driver = _make_driver()
    try:
        data = _get_page_data(driver, "https://www.finn.no/job/search")
        raw_filters = data["queries"][0]["state"]["data"]["filters"]

        result = {}
        for f in raw_filters:
            name = f["name"]
            items = f.get("filter_items", [])
            if not items:
                continue

            if name == "location":
                parsed = []
                for item in items:  # country level
                    entry = {"label": item["display_name"], "value": item["value"]}
                    counties = []
                    for county in item.get("filter_items", []):  # county level
                        c = {"label": county["display_name"], "value": county["value"]}
                        municipalities = [
                            {"label": m["display_name"], "value": m["value"]}
                            for m in county.get("filter_items", [])
                        ]
                        if municipalities:
                            c["children"] = municipalities
                        counties.append(c)
                    if counties:
                        entry["children"] = counties
                    parsed.append(entry)
                result[name] = parsed
            else:
                result[name] = [
                    {"label": i["display_name"], "value": i["value"]}
                    for i in items
                ]

        _filters_cache = result
        return result
    finally:
        driver.quit()


def _extract_jobs_from_page(driver: webdriver.Chrome, url: str) -> tuple[list[dict], int]:
    data = _get_page_data(driver, url)
    state = data["queries"][0]["state"]["data"]
    last_page = state["metadata"]["paging"]["last"]

    jobs = []
    for doc in state["docs"]:
        if doc.get("type") != "job":
            continue
        jobs.append({
            "title": doc.get("job_title") or doc.get("heading", ""),
            "employer": doc.get("company_name", ""),
            "location": doc.get("location", ""),
            "url": doc.get("canonical_url", f"https://www.finn.no/job/ad/{doc['id']}"),
            "deadline": doc.get("deadline"),
            "published": doc.get("published"),
        })

    return jobs, last_page


def scrape_finn(params: dict) -> list[dict]:
    qs = urlencode(params, doseq=True)
    base_url = "https://www.finn.no/job/search" + (f"?{qs}" if qs else "")
    sep = "&" if qs else "?"

    driver = _make_driver()
    try:
        all_jobs, last_page = _extract_jobs_from_page(driver, base_url)
        for page in range(2, last_page + 1):
            page_jobs, _ = _extract_jobs_from_page(driver, f"{base_url}{sep}page={page}")
            all_jobs.extend(page_jobs)
        return all_jobs
    finally:
        driver.quit()


_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


async def _fetch_description(url: str, client: httpx.AsyncClient, sem: asyncio.Semaphore) -> str:
    async with sem:
        try:
            resp = await client.get(url, timeout=10, follow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            article = soup.find("article")
            if article:
                return article.get_text(separator="\n", strip=True)
        except Exception:
            pass
        return ""


async def fetch_descriptions(urls: list[str]) -> list[str]:
    """Fetch job ad descriptions in parallel (max 8 concurrent)."""
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(headers=_HEADERS) as client:
        return await asyncio.gather(*[_fetch_description(url, client, sem) for url in urls])


if __name__ == "__main__":
    jobs = scrape_finn({"q": "systemutvikler"})
    print(json.dumps(jobs, indent=2, ensure_ascii=False))
    print(f"\nTotal: {len(jobs)}", flush=True)
