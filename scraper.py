import requests
from bs4 import BeautifulSoup
import json
import time

BASE_URL = "https://aitoolfor.org"

def get_soup(url):
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def scrape_tool_page(url):
    soup = get_soup(url)

    title = soup.find("h1")
    description = soup.find("p")

    return {
        "url": url,
        "title": title.text.strip() if title else None,
        "description": description.text.strip() if description else None
    }

def scrape_directory():
    soup = get_soup(BASE_URL)
    tools = []

    for link in soup.find_all("a", href=True):
        href = link["href"]
        # Simple heuristic: links that point to tool pages are usually like /toolname/...
        if href.startswith("/") and href.count("/") >= 2:
            full_url = BASE_URL + href

            try:
                print(f"Scraping: {full_url}")
                tool_data = scrape_tool_page(full_url)
                tools.append(tool_data)
                time.sleep(1)  # Be polite
            except Exception as e:
                print("Error:", e)

    return tools

if __name__ == "__main__":
    data = scrape_directory()

    with open("aitools.json", "w") as f:
        json.dump(data, f, indent=2)

    print(f"Scraped {len(data)} tools.")
