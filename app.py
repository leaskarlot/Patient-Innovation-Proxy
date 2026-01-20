import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

ALLOWED_HOSTS = {"patient-innovation.com", "www.patient-innovation.com"}

app = FastAPI(title="Patient Innovation Proxy")

class SearchRequest(BaseModel):
    query: str

class FetchRequest(BaseModel):
    url: str

def assert_allowed(url: str):
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(400, "Only https allowed")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise HTTPException(403, "Host not allowed")

def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

@app.post("/search")
async def search(req: SearchRequest):
    url = f"https://patient-innovation.com/?s={req.query}"
    assert_allowed(url)

    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "MyHealthBot/1.0"}) as client:
        r = await client.get(url)

    if r.status_code != 200:
        raise HTTPException(502, "Upstream error")

    soup = BeautifulSoup(r.text, "html.parser")

    results = []
    seen = set()

    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        if not href:
            continue

        # Nur patient-innovation.com Links
        if href.startswith("/"):
            full_url = "https://patient-innovation.com" + href
        elif href.startswith("https://patient-innovation.com") or href.startswith("https://www.patient-innovation.com"):
            full_url = href
        else:
            continue

        if full_url in seen:
            continue
        seen.add(full_url)

        title = a.get_text(" ", strip=True)
        if not title or len(title) < 10:
            continue

        results.append({
            "title": title,
            "url": full_url
        })

    # Innovationen priorisieren (falls erkennbar)
    results.sort(key=lambda x: 0 if "innovation" in x["url"].lower() else 1)

    return {
        "query": req.query,
        "search_url": url,
        "results": results[:15]  # max. 15 direkte Referenzen
    }


@app.post("/fetch")
async def fetch(req: FetchRequest):
    assert_allowed(req.url)

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(req.url)

    if r.status_code != 200:
        raise HTTPException(502, "Upstream error")

    return {
        "url": req.url,
        "text": extract_text(r.text)[:15000]
    }
