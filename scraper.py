import requests
from bs4 import BeautifulSoup
import json
import time
import re
from urllib.parse import urljoin

BASE_URL = "https://aitoolfor.org"

# -------- HTTP helpers --------

def get_soup(url, retries=3, backoff=3):
    """Fetch a URL and return BeautifulSoup object, with simple retries."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                url,
                timeout=20,
                headers={
                    "User-Agent": "ai-tools-scraper/1.0 (github.com/chuck-aicx)"
                },
            )
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"[WARN] ({attempt}/{retries}) Error fetching {url}: {e}")
            if attempt == retries:
                raise
            time.sleep(backoff * attempt)
    # Should never get here
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def make_full_url(href: str) -> str:
    """Convert relative URLs to absolute URLs."""
    if not href:
        return None
    return urljoin(BASE_URL, href)


# -------- Parsing helpers --------

def parse_metric(raw: str):
    """
    Convert metrics like '5K', '32.0K', '174M', '1.66B' into an integer.
    Returns (raw_value, numeric_value or None).
    """
    if not raw:
        return None, None
    text = raw.strip()

    # e.g. "5K", "32.0K", "174M", "1.66B", "1.3K"
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)([KMB])$", text, re.IGNORECASE)
    if not m:
        # Maybe it's already a plain number like "1234"
        if text.isdigit():
            try:
                return text, int(text)
            except Exception:
                return text, None
        return text, None

    num = float(m.group(1))
    suffix = m.group(2).upper()

    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
    return text, int(num * multiplier)


def parse_category_list_item(text: str):
    """
    Parse the text from the category list (e.g. 'ToolName 5K 1233 Description…').

    Heuristic:
    - Split around ' 1233 ' → left side: name + possible metric, right side: description.
    - If the last token on the left looks like a metric (5K, 32.0K, etc.), treat it as such.
    """
    if not text:
        return None, None, None, None

    normalized = " ".join(text.split())
    marker = " 1233 "

    name = normalized
    metric_raw = None
    description = ""
    metric_value = None

    if marker in normalized:
        before, after = normalized.split(marker, 1)
        description = after.strip()

        parts = before.split()
        if parts:
            last = parts[-1]
            # Does last token look like a metric?
            if re.match(r"^[0-9]+(?:\.[0-9]+)?[KMB]?$", last, re.IGNORECASE):
                metric_raw, metric_value = parse_metric(last)
                name = " ".join(parts[:-1]) if len(parts) > 1 else before
            else:
                name = before.strip()
    else:
        name = normalized

    return name, metric_raw, metric_value, description


# -------- Tool-page scraper --------

def scrape_tool_page(tool_url: str):
    """
    Scrape an individual tool page for richer metadata:
    - Title (h1 or <title>)
    - Meta description
    - og:image / twitter:image / first <img>
    - Optional tags (categories, if any)
    """
    soup = get_soup(tool_url)

    # Title
    h1 = soup.find("h1")
    page_title = h1.get_text(strip=True) if h1 else None

    if not page_title:
        title_tag = soup.find("title")
        if title_tag:
            page_title = title_tag.get_text(strip=True)

    # Meta description
    meta_desc = None
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        meta_desc = md["content"].strip()

    # og:description as fallback
    if not meta_desc:
        ogd = soup.find("meta", attrs={"property": "og:description"})
        if ogd and ogd.get("content"):
            meta_desc = ogd["content"].strip()

    # Image (og:image > twitter:image > first <img>)
    image_url = None
    og_img = soup.find("meta", attrs={"property": "og:image"})
    if og_img and og_img.get("content"):
        image_url = make_full_url(og_img["content"])
    if not image_url:
        tw_img = soup.find("meta", attrs={"name": "twitter:image"})
        if tw_img and tw_img.get("content"):
            image_url = make_full_url(tw_img["content"])
    if not image_url:
        img = soup.find("img")
        if img and img.get("src"):
            image_url = make_full_url(img["src"])

    # Tags (very heuristic – optional)
    tags = []
    for tag_link in soup.select("a[href]"):
        href = tag_link["href"]
        if "/categories/" in href or "/tags/" in href:
            tag_text = tag_link.get_text(" ", strip=True)
            if tag_text and tag_text.lower() not in {"home", "categories"}:
                tags.append(tag_text)
    # Deduplicate tags
    tags = sorted(set(tags))

    return {
        "page_title": page_title,
        "page_meta_description": meta_desc,
        "image_url": image_url,
        "tags": tags,
    }


# -------- Category discovery & scraping --------

def discover_categories():
    """
    Discover all category URLs from the categories index page.
    Returns a list of dicts: [{slug, url}, ...]
    """
    index_url = f"{BASE_URL}/categories/"
    soup = get_soup(index_url)
    categories = {}

    # The category index uses anchor links under /categories/<slug>/
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if "/categories/" not in href:
            continue
        full = make_full_url(href)
        slug = full.rstrip("/").split("/")[-1]
        if slug and slug not in categories:
            categories[slug] = full

    cat_list = [{"slug": slug, "url": url} for slug, url in categories.items()]
    print(f"[INFO] Discovered {len(cat_list)} categories.")
    for c in cat_list:
        print(f"  - {c['slug']}: {c['url']}")
    return cat_list


def scrape_category_page(category_slug: str, url: str, seen_urls: set):
    """
    Scrape a single category page (which contains the text list of tools).
    Returns a list of tool dicts with basic fields, optionally enriched by tool pages.
    """
    soup = get_soup(url)

    h1 = soup.find("h1")
    if not h1:
        print(f"[WARN] No <h1> on category page: {url}")
        return []

    ul = h1.find_next("ul")
    if not ul:
        print(f"[WARN] No <ul> after <h1> on category page: {url}")
        return []

    tools = []

    for a in ul.find_all("a", href=True):
        raw_text = a.get_text(" ", strip=True)
        name, metric_raw, metric_value, preview_desc = parse_category_list_item(raw_text)

        tool_href = a["href"]
        tool_url = make_full_url(tool_href)

        if tool_url in seen_urls:
            continue  # dedupe by URL
        seen_urls.add(tool_url)

        # Base record from category list
        record = {
            "category": category_slug,
            "name": name,
            "metric_raw": metric_raw,
            "metric_value_estimate": metric_value,
            "description_preview": preview_desc,
            "url": tool_url,
            "raw_text": raw_text,
        }

        # Enrich from the tool page (title, meta description, image, tags)
        try:
            page_data = scrape_tool_page(tool_url)
            record.update(page_data)
        except Exception as e:
            print(f"[WARN] Failed to enrich tool page {tool_url}: {e}")

        tools.append(record)

    return tools


def scrape_category_with_pagination(category):
    """
    Scrape all pages for a given category by incrementing ?page=N until there's no UL list.
    """
    slug = category["slug"]
    base_url = category["url"]

    print(f"\n[INFO] Scraping category '{slug}' at {base_url}")
    all_tools = []
    seen_urls = set()
    page = 1

    while True:
        page_url = f"{base_url}?page={page}"
        print(f"[INFO]  -> Category page {page}: {page_url}")

        try:
            page_tools = scrape_category_page(slug, page_url, seen_urls)
        except Exception as e:
            print(f"[WARN] Error scraping category page {page_url}: {e}")
            break

        if not page_tools:
            if page == 1:
                # Some categories may not use pagination; try base URL without ?page=
                if base_url != page_url:
                    try:
                        print(f"[INFO]  -> No tools with ?page=1, trying base URL {base_url}")
                        page_tools = scrape_category_page(slug, base_url, seen_urls)
                    except Exception as e:
                        print(f"[WARN] Error scraping base category URL {base_url}: {e}")
                # If still nothing, stop
            if not page_tools:
                print(f"[INFO]  -> No more tools for '{slug}'. Stopping pagination.")
                break

        all_tools.extend(page_tools)

        # Polite delay to avoid hammering the site
        time.sleep(0.4)
        page += 1

    print(f"[INFO] Finished category '{slug}' with {len(all_tools)} tools.")
    return all_tools


# -------- Main entry point --------

if __name__ == "__main__":
    print("[INFO] Starting full scrape of aitoolfor.org")

    categories = discover_categories()
    all_tools = []

    for cat in categories:
        cat_tools = scrape_category_with_pagination(cat)
        all_tools.extend(cat_tools)

    # Optional: sort by category then name for consistency
    all_tools.sort(key=lambda t: (t.get("category") or "", t.get("name") or ""))

    output_file = "aitools.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_tools, f, indent=2, ensure_ascii=False)

    print(f"\n[INFO] DONE — scraped {len(all_tools)} tools across {len(categories)} categories.")
    print(f"[INFO] Output written to {output_file}")
