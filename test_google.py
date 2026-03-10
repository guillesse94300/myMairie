# Test script to debug Google search scraping
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
from urllib.parse import unquote

cookies = {
    "CONSENT": "YES+",
    "SOCS": "CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjUwMzA1LjA5X3AxGgJmciADGgYIgPy8sQY",
}

resp = curl_requests.get(
    "https://www.google.com/search",
    params={"q": "pierrefonds .pdf", "num": 10, "hl": "fr"},
    impersonate="chrome",
    cookies=cookies,
    timeout=15,
)

soup = BeautifulSoup(resp.text, "html.parser")

# Method 1: all <a> tags with href
all_a = soup.find_all("a", href=True)
print(f"Total <a> tags: {len(all_a)}")

pdf_links = []
for a in all_a:
    href = a["href"]
    if ".pdf" in href.lower():
        pdf_links.append(href)
    # Also check /url?q= redirects pointing to PDF
    if "/url?" in href and ".pdf" in href.lower():
        pdf_links.append(href)

print(f"PDF <a> links: {len(pdf_links)}")
for h in pdf_links:
    print(f"  {h[:150]}")

# Method 2: find in text
text = resp.text
count = text.lower().count(".pdf")
print(f"\n.pdf occurrences in HTML: {count}")

# Method 3: find cite elements (Google shows URLs in <cite> tags)
cites = soup.find_all("cite")
print(f"\n<cite> elements: {len(cites)}")
for c in cites:
    t = c.get_text(strip=True)
    print(f"  {t[:100]}")

# Method 4: Show sample of external links
ext = [a for a in all_a if a["href"].startswith("http") and "google" not in a["href"]]
print(f"\nExternal links: {len(ext)}")
for a in ext[:10]:
    print(f"  {a['href'][:120]}")
