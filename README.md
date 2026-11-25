# 🚀 Google Scholar Scraper

Google Scholar Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Google Scholar data for free.

## ✨ What Can I Get?

- 📚 **6.7M+ papers for "large language models" alone** — title, authors with profile ids, journal, year, citation count, versions, PDF links and snippet
- 🔗 **284K+ papers citing "Attention Is All You Need"** — who cites any paper, citations per year, every version, related papers and ready-made MLA / APA / BibTeX citations
- 👩‍🔬 **Full author profiles, down to all 841 of Geoffrey Hinton's papers** — citations, h-index, i10-index, citations per year, interests, homepage and co-authors
- ⚖️ **US court opinions since 1791 & 5,600+ top journals ranked** — full opinion text, citations, court and year; h5-index of the top publications in 265 fields and 11 languages

## 📄 Example: A Full Google Scholar Search

```json
{
  "query": "large language models",
  "total_results_estimate": 6700000,
  "related_searches": ["emergent large language models", "large language models abilities", "prompt large language models"],
  "results": [
    {
      "id": "o93zfHYlUTIJ",
      "cluster_id": "3625720365842685347",
      "title": "A survey on evaluation of large language models",
      "link": "https://dl.acm.org/doi/abs/10.1145/3641289",
      "authors": [
        { "name": "Y Chang", "id": "Hw-lrpAAAAAJ", "link": "https://scholar.google.com/citations?user=Hw-lrpAAAAAJ&hl=en" },
        { "name": "X Wang", "id": "Q7Ieos8AAAAJ", "link": "https://scholar.google.com/citations?user=Q7Ieos8AAAAJ&hl=en" }
      ],
      "has_more_authors": true,
      "year": 2024,
      "source": "dl.acm.org",
      "publication_summary": "Y Chang, X Wang, J Wang, Y Wu, L Yang… - ACM transactions on …, 2024 - dl.acm.org",
      "snippet": "… 3.1 Natural Language Processing Tasks … the development of language models, particularly large language models, was to enhance performance on natural language processing tasks, …",
      "cited_by_count": 7198,
      "versions_count": 11,
      "resources": [{ "type": "pdf", "source": "acm.org", "link": "https://dl.acm.org/doi/pdf/10.1145/3641289" }],
      "cited_by_link": "https://scholar.google.com/scholar?cites=3625720365842685347&hl=en",
      "versions_link": "https://scholar.google.com/scholar?cluster=3625720365842685347&hl=en",
      "related_link": "https://scholar.google.com/scholar?q=related:o93zfHYlUTIJ:scholar.google.com/&hl=en"
    }
  ]
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Google Scholar Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/google-scholar-scraper
cd google-scholar-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

Google Scholar asks every new visitor to pass a script check, so the first request opens Google Chrome for a few seconds to earn the cookie that lets you in. Every request after that is plain HTTP. You need Google Chrome installed.

Running thousands of calls from one IP? Google Scholar answers it with a reCAPTCHA. Set `GOOGLE_SCHOLAR_PROXY=http://user:pass@host:port` to a datacenter proxy (a US one for the case-law endpoints) and keep going.

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/articles/search?query=large+language+models"
```

```json
{
  "query": "large language models",
  "total_results_estimate": 6700000,
  "results": [
    {
      "id": "o93zfHYlUTIJ",
      "title": "A survey on evaluation of large language models",
      "link": "https://dl.acm.org/doi/abs/10.1145/3641289",
      "authors": [
        { "name": "Y Chang", "id": "Hw-lrpAAAAAJ", "link": "https://scholar.google.com/citations?user=Hw-lrpAAAAAJ&hl=en" }
      ],
      "year": 2024,
      "source": "dl.acm.org",
      "cited_by_count": 7198,
      "versions_count": 11,
      "resources": [{ "type": "pdf", "source": "acm.org", "link": "https://dl.acm.org/doi/pdf/10.1145/3641289" }],
      "cited_by_link": "https://scholar.google.com/scholar?cites=3625720365842685347&hl=en"
    }
  ]
}
```

All 16 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

16 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Search Articles | `/articles/search` | Papers with authors, journal, year, citations, versions and PDF links |
| Search Suggestions | `/articles/suggestions` | What the search box suggests for your words |
| Citing Articles | `/articles/cited-by` | Every paper citing an article, plus its citations per year |
| Cite Article | `/articles/cite` | MLA, APA, Chicago, Harvard, Vancouver and BibTeX in one call |
| Article Versions / Related | `/articles/versions`, `/articles/related` | Every version of a paper and the papers most like it |
| Article Details | `/articles/details` | A profile paper in full: abstract, volume, citations per year |
| Author Profile | `/authors/details` | Citations, h-index, i10-index, interests, homepage and co-authors (website contacts: hosted API only) |
| Author Articles / Co-Authors | `/authors/articles`, `/authors/co-authors` | Every paper of an author, 100 a page, and every co-author |
| Search Authors | `/authors/search` | The author profiles that match a name |
| Search Case Law / Court Opinion | `/cases/search`, `/cases/details` | US court opinions since 1791, with the full opinion text |
| Top Publications / Search Publications | `/publications/top`, `/publications/search` | Top journals and conferences ranked by h5-index |
| Publication Top Articles | `/publications/articles` | A journal's or conference's most cited papers |


## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-google-scholar-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-google-scholar-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-google-scholar-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/articles/search",
    params={"query": "large language models"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Google Scholar Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/google-scholar-scraper-github-whatsapp)

[![Ask Us by Email about Google Scholar Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Google%20Scholar%20Scraper%20API&body=I%20need%20help%20using%20the%20Google%20Scholar%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/google-scholar-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/google-scholar-scraper)
