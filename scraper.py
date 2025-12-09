import requests
from bs4 import BeautifulSoup
import json
import time
import re

BASE_URL = "https://aitoolfor.org"

# Categories to scrape (you can add more)
CATEGORIES = [
    {"slug": "assistant", "url": f"{BASE_URL}/categories/assistant/"},
]

def get_soup(url):
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

def parse_tool_text(text):
    text = " ".join(text.split())
    name = text
    metric = None
    description = ""

    marker = " 1233 "
    if marker in text:
        before, after = text.split(marker, 1)
        description = after.strip()
        parts = before.split()
        if parts:
            last = parts[-1]
            if re.match(r"^[0-9]+(\.[0-9]+)?[KMB]?$", last):
                metric = last
                name = " ".join(parts[:-1]) if len(parts) > 1 else before
            else:
                name = before.strip()
    else:
        name = text.strip()

    return name, metric, description

def scrape_category(slug, url):
    print(f"Scraping category {slug}: {url}")
    soup = get_soup(url)
    results = []

    h1 = soup.find("h1")
    if not h1:
        return results

    ul = h1.find_next("ul")
    if not ul:
        return results

    for a in ul.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if not text:
            continue

        name, metric, desc = parse_tool_text(text)
        tool_url = a["href"]
        if tool_url.startswith("/"):
            tool_url = BASE_URL + tool_url

        results.append({
            "category": slug,
            "name": name,
            "metric": metric,
            "description": desc,
            "url": tool_url,
            "raw_text": text
        })

    return results

def scrape_all():
    data = []
    for cat in CATEGORIES:
        time.sleep(1)
        data.extend(scrape_category(cat["slug"], cat["url"]))
    return data

if __name__ == "__main__":
    output = scrape_all()
    with open("aitools.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Scraped {len(output)} items.")
