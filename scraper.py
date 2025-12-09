import requests
from bs4 import BeautifulSoup
import json
import time
import re

BASE_URL = "https://aitoolfor.org"

# 🔧 Categories you want to scrape.
# For now we only scrape "assistant".
# To add more later, just add new dicts here.
CATEGORIES = [
    {
        "slug": "assistant",
        "url": f"{BASE_URL}/categories/assistant/",
    },
    # Example to enable later:
    # {"slug": "agents", "url": f"{BASE_URL}/categories/agents/"},
]


def get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_tool_text(text: str):
    """
    The category pages have entries like:
      'Ecommerce Tools AI 5K  1233  Ecommerce Tools AI is your all-in-one platform ...'

    Heuristic:
      - Split on ' 1233 ' (this constant appears in almost all entries)
      - Left side: name [+ optional metric like 5K, 1.66B, etc.]
      - Right side: description
    """
    text = " ".join(text.split())  # collapse whitespace

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
            # If last token looks like a number like "5K", "1.66B", "174M", treat it as metric
            if re.match(r"^[0-9]+(\.[0-9]+)?[KMB]?$", last):
                metric = last
                name = " ".join(parts[:-1]) if len(parts) > 1 else before
            else:
                name = before.strip()
    else:
        # Fallback: no marker found, treat the whole text as the name
        name = text.strip()

    return name, metric, description


def scrape_category(category_slug: str, url: str):
    print(f"Scraping category '{category_slug}' from {url}")
    soup = get_soup(url)

    results = []

    # Find the main heading for the page (e.g. "Assistant AI tools")
    h1 = soup.find("h1")
    if not h1:
        print(f"WARNING: no <h1> found on {url}")
        return results

    # Heuristic: the first <ul> after the main heading holds the tools
    ul = h1.find_next("ul")
    if not ul:
        print(f"WARNING: no <ul> of tools found after <h1> on {url}")
        return results

    for a in ul.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if not text:
            continue

        tool_name, metric, description = parse_tool_text(text)

        tool_url = a["href"]
        # Normalize relative URLs if any appear
        if tool_url.startswith("/"):
            tool_url = BASE_URL + tool_url

        results.append(
            {
                "category": category_slug,
                "name": tool_name,
                "metric": metric,
                "description": description,
                "url": tool_url,
                "raw_text": text,
            }
        )

    return results


def scrape_all_categories():
    all_tools = []
    for cat in CATEGORIES:
        time.sleep(1)  # be gentle to the site
        tools = scrape_category(cat["slug"], cat["url"])
        all_tools.extend(tools)
    return all_tools


if __name__ == "__main__":
    data = scrape_all_categories()

    with open("aitools.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Scraped {len(data)} tools in total.")
