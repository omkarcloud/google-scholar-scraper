"""HTML / JSON -> clean dicts for every /google-scholar/* endpoint. Pure
functions, no I/O.

Fixtures (google_scholar/fixtures/, raw answers of scholar.google.com as it
sent them, captured 2026-11-24 and 2026-11-25 over curl through proxy exits;
the larger ones are kept packed, `name.html.gz`):

  search_*.html            /scholar?q=            (10 rows; a book, a PDF, a [CITATION] row, patents, the one-result
                                                    layout and the same search with lookup=0, the author-profile
                                                    block, the French interface, a page past the end, a search
                                                    with no result, the date order, library links next to the PDF)
  cited_by*.html           /scholar?cites=        (a deep page that came back empty; an unknown id)
  versions*.html           /scholar?cluster=      related*.html   /scholar?q=related:<id>:scholar.google.com/
  cite.html, cite.bib      /scholar?q=info:<id>:scholar.google.com/&output=cite and its BibTeX export
  suggestions*.json        /scholar_complete
  author*.html             /citations?user=       (a profile without citations; page 2; past the end)
  co_authors*.html         /citations?view_op=list_colleagues
  article*.html            /citations?view_op=view_citation
  case_search*.html, case*.html                   /scholar?as_sdt=2006 (also in date order: opinions without a
                                                    reporter citation yet) and /scholar_case?case=
  publications_*.html, publication_*.html         Scholar Metrics: top_venues, search_venues, list_hcore
  refused_*.html           the three refusal pages (fetch.py's fixtures, not data)

The result pages are read by link and class, never by label, so a page in
another interface language parses the same ("Cité 4102 fois" is still a
link to cites=). The profile, article, case and metrics pages are always
asked for in English.
"""
import json
import re
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

from lxml import html as lxml_html

from google_scholar import refs
from scraper_utils.pages import page_title as _raw_page_title
from scraper_utils.text import clean, html_to_text
from scraper_utils.values import first_int

KIND_NAMES = {"b": "book", "c": "citation"}       # the short tag of a row: [B], [C], [PDF], [HTML], [DOC]...
DOMAIN_RE = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", re.I)
YEAR_END_RE = re.compile(r"(?:^|,\s*)((?:1[5-9]|20)\d\d)$")
NUMBER_RE = re.compile(r"\d[\d.,   ]*\d|\d")
TIME_NOTE_RE = re.compile(r"[\(（][^\)）]*[\)）]")
ARTICLE_FIELDS = {       # the labels of a "View article" page (English interface) -> our keys
    "authors": "authors", "inventors": "authors", "publication date": "publication_date", "journal": "journal",
    "conference": "conference", "book": "book", "source": "source", "publisher": "publisher", "volume": "volume",
    "issue": "issue", "pages": "pages", "description": "description", "patent office": "patent_office",
    "patent number": "patent_number", "application number": "application_number", "institution": "institution",
    "report number": "report_number",
}


# ---- small readers -------------------------------------------------------------------

def page_title(html):
    """The page's <title> as text (entities decoded); None without one."""
    return clean(_raw_page_title(html))


def _doc(html):
    return lxml_html.fromstring(html if (html or "").strip() else "<html></html>")


def _cls(name):
    return f'contains(concat(" ", normalize-space(@class), " "), " {name} ")'


def _text(el):
    """The element's text, whitespace collapsed; None when empty."""
    return clean(el.text_content()) if el is not None else None


def _first(el, xpath):
    found = el.xpath(xpath)
    return found[0] if found else None


def _param(href, name):
    if not href:
        return None
    values = parse_qs(urlsplit(href.replace("&amp;", "&")).query).get(name)
    return values[0] if values else None


def _count(text):
    """The first whole number in a text, grouping marks dropped ('Cited by 16,569' -> 16569)."""
    found = NUMBER_RE.search(text or "")
    return int(re.sub(r"\D", "", found.group(0))) if found else None


def _year(value):
    number = first_int(value)
    return number if number and 1000 <= number <= 2100 else None


def _domain(text):
    found = DOMAIN_RE.findall(text or "")
    return found[-1].lower() if found else None


def _total(text):
    """'About 6,030,000 results (0.07 sec)' / 'Page 2 of about 7,884 results'
    / 'Environ 6 520 000 résultats (0,08 s)' -> the result count: the
    largest number once the time note is dropped. None without a line."""
    numbers = [int(re.sub(r"\D", "", n)) for n in NUMBER_RE.findall(TIME_NOTE_RE.sub(" ", text or ""))]
    return max(numbers) if numbers else None


def _split_names(text):
    names = [clean(n) for n in re.split(r",\s*", (text or "").replace("…", "").replace("...", ""))]
    return [n for n in names if n]


def _per_year(doc, year_class, bar_class, value_class=None):
    """A citations-per-year chart: every bar is placed by its z-index, counted
    from the last year; a year without citations has no bar."""
    years = [_year(t) for t in doc.xpath(f'//span[@class="{year_class}"]/text()')]
    counts = {}
    for bar in doc.xpath(f'//a[{_cls(bar_class)}]'):
        found = re.search(r"z-index:\s*(\d+)", bar.get("style") or "")
        value = _count(_text(_first(bar, f'.//span[@class="{value_class}"]')) if value_class else _text(bar))
        if found and value is not None and 0 < int(found.group(1)) <= len(years):
            counts[years[len(years) - int(found.group(1))]] = value
    return [{"year": year, "citations": counts.get(year, 0)} for year in years if year]


# ---- a result page -------------------------------------------------------------------

def _row_title(h3):
    """(title, kind) of a row heading: the title without its [BOOK][B] tags."""
    kind = None
    short = clean(" ".join(h3.xpath('.//span[@class="gs_ct2"]/text()')))
    if short:
        token = short.strip("[]").lower()
        kind = KIND_NAMES.get(token, token)
    bare = deepcopy(h3)
    for tag in bare.xpath('.//span[@class="gs_ctc" or @class="gs_ctu"]'):
        tag.drop_tree()          # keeps the text that follows the tag
    return clean(bare.text_content()), kind


def _grey_line(row):
    """The grey line under a title: 'authors - publication, year - source'
    -> its text and its parts (any of them None)."""
    line = _first(row, f'.//div[{_cls("gs_a")}]')
    text = _text(line)
    if not text:
        return {"summary": None, "authors": [], "authors_truncated": False, "publication": None, "year": None, "source": None}
    parts = [p.strip() for p in text.split(" - ")]
    authors_text = parts[0]
    source = parts[-1] if len(parts) >= 3 else None
    middle = " - ".join(parts[1:-1]) if len(parts) >= 3 else (parts[1] if len(parts) == 2 else "")
    year = None
    found = YEAR_END_RE.search(middle)
    if found:
        year = int(found.group(1))
        middle = middle[:found.start()].rstrip(", ")
    ids = {}
    for a in line.xpath('.//a[contains(@href, "user=")]'):
        ids[clean(a.text_content())] = _param(a.get("href"), "user")
    authors = [{"name": name, "id": ids.get(name), "link": refs.author_link(ids.get(name))} for name in _split_names(authors_text)]
    return {"summary": text, "authors": authors, "authors_truncated": "…" in authors_text or "..." in authors_text,
            "publication": clean(middle.replace("…", "").strip(" ,")) if middle else None, "year": year, "source": source}


LIBRARY_LINK = "output=instlink"     # "Full-Text @ <a university>", "Full View": the library of the network the request came from


def _resources(row):
    """The full texts Scholar links to (a PDF, an HTML page). The links to a
    library's own catalogue are left out: Scholar adds those for the network
    a request comes from (Korean and Taiwanese universities through our
    exits), so they say nothing about the paper."""
    out = []
    for a in row.xpath(f'.//div[{_cls("gs_or_ggsm")}]//a[@href]'):
        if LIBRARY_LINK in (a.get("href") or ""):
            continue
        tag = clean(" ".join(a.xpath('.//span[@class="gs_ctg2"]/text()')))
        text = _text(a) or ""
        out.append({"type": tag.strip("[]").lower() if tag else None,
                    "source": clean(text.replace(tag or "", "", 1)) if text else None, "link": refs.absolute(a.get("href"))})
    return out


def _snippet(row):
    block = _first(row, f'.//div[{_cls("gs_rs")}]')
    if block is None:
        return None, None
    age = _text(_first(block, './/span[@class="gs_age"]'))
    text = _text(block) or ""
    if age and text.startswith(age):
        text = text[len(age):]
    return clean(text), clean((age or "").rstrip(" -")) or None


def _footer(row):
    """The links under a row, told apart by where they lead (never by label)."""
    out = {"cited_by_count": None, "cited_by_ids": None, "versions_count": None, "related": False, "cached_link": None,
           "how_cited_link": None}
    for a in row.xpath(f'.//div[{_cls("gs_fl")}]//a[@href]'):
        href = a.get("href") or ""
        if "cites=" in href:
            out["cited_by_count"] = _count(_text(a))
            out["cited_by_ids"] = _param(href, "cites")
        elif "cluster=" in href:
            out["versions_count"] = _count(_text(a))
        elif "q=related:" in href:
            out["related"] = True
        elif "q=cache:" in href:
            out["cached_link"] = refs.absolute(href)
        elif "scholar_case?about=" in href:
            out["how_cited_link"] = refs.absolute(href)
    return out


def _article_row(row):
    text_id = row.get("data-cid") or row.get("data-did") or None
    number = refs.id_to_number(text_id)
    h3 = _first(row, f'.//h3[{_cls("gs_rt")}]')
    title, kind = _row_title(h3)
    link = next((refs.absolute(h) for h in h3.xpath(".//a/@href") if refs.absolute(h)), None)
    grey = _grey_line(row)
    snippet, published_ago = _snippet(row)
    footer = _footer(row)
    return {
        "id": text_id,
        "cluster_id": number,
        "type": kind,
        "title": title,
        "link": link,
        "authors": grey["authors"],
        "has_more_authors": grey["authors_truncated"],
        "publication": grey["publication"],
        "year": grey["year"],
        "source": grey["source"],
        "publication_summary": grey["summary"],
        "snippet": snippet,
        "abstract": _text(_first(row, f'.//div[{_cls("gs_fma_snp")}]')),
        "published_ago": published_ago,
        "cited_by_count": footer["cited_by_count"],
        "versions_count": footer["versions_count"],
        "resources": _resources(row),
        "cited_by_link": refs.cited_by_link(footer["cited_by_ids"]),
        "versions_link": refs.versions_link(number) if footer["versions_count"] else None,
        "related_link": refs.related_link(text_id) if footer["related"] else None,
        "cached_link": footer["cached_link"],
    }


def _case_row(row):
    h3 = _first(row, f'.//h3[{_cls("gs_rt")}]')
    href = next(iter(h3.xpath('.//a[contains(@href, "scholar_case")]/@href')), None)
    number = _param(href, "case") or refs.id_to_number(row.get("data-did"))
    text = _text(_first(row, f'.//div[{_cls("gs_a")}]')) or ""
    # 'reporter citations - court, year - Google Scholar'; a new opinion has no reporter citation yet
    parts = [p.strip() for p in text.split(" - ")]
    if len(parts) > 1:
        parts = parts[:-1]              # the source, always the site itself
    court_part = parts[-1] if parts else ""
    cited_as = parts[0] if len(parts) > 1 else ""
    year = None
    found = YEAR_END_RE.search(court_part)
    if found:
        year, court_part = int(found.group(1)), court_part[:found.start()].rstrip(", ")
    snippet, _ = _snippet(row)
    footer = _footer(row)
    return {
        "id": number,
        "name": _row_title(h3)[0],
        "link": refs.case_link(number),
        "citations": _split_names(cited_as),
        "court": clean(court_part) or None,
        "year": year,
        "citation_summary": text or None,
        "snippet": snippet,
        "cited_by_count": footer["cited_by_count"],
        "versions_count": footer["versions_count"],
        "cited_by_link": refs.cited_by_link(footer["cited_by_ids"]),
        "how_cited_link": footer["how_cited_link"],
    }


def _profiles(doc):
    """The "User profiles for …" block a search page shows above its rows."""
    out = []
    for h4 in doc.xpath('//div[@id="gs_res_ccl_mid"]//h4[@class="gs_rt2"]'):
        a = _first(h4, ".//a[@href]")
        author_id = _param(a.get("href"), "user") if a is not None else None
        box = h4.getparent()
        rest = clean(" ".join(t for t in box.itertext()).replace(_text(h4) or "", "", 1)) or ""
        affiliation = None
        if box.tag == "td":          # one profile: the affiliation has a line of its own
            affiliation = _text(_first(box, './div[@class="gs_nph"]'))
            rest = rest.replace(affiliation or "", "", 1) if affiliation else rest
        numbers = NUMBER_RE.findall(DOMAIN_RE.sub(" ", rest))
        out.append({"id": author_id, "name": _text(h4), "link": refs.author_link(author_id), "affiliation": affiliation,
                    "email_domain": _domain(rest), "cited_by_count": int(re.sub(r"\D", "", numbers[-1])) if numbers else None})
    return out


def _history(doc):
    """The "Citations" chart of a cited-by page: how many of the citing
    articles each year has. The dialog holds every year, the sidebar the
    last four; [] on a page without the chart."""
    for chart in ("gs_rs_hist_dialog", "gs_rs_hist_sidebar"):
        box = _first(doc, f'//div[@id="{chart}"]')
        if box is None:
            continue
        counts = {_year(bar.get("data-year")): _count(bar.get("data-count")) for bar in box.xpath(".//*[@data-year][@data-count]")}
        years = [_year(t) for t in box.xpath('.//span[@class="gs_hist_g_t"]/text()')] or sorted(y for y in counts if y)
        if counts:
            return [{"year": year, "citations": counts.get(year) or 0} for year in years if year]
    return []


def parse_results(html, start=0, cases=False):
    """One /scholar result page -> {total_count, rows, profiles,
    related_searches, citations_per_year, is_best_result, has_next, has_pager}. `start` is the offset that was
    asked for (the pager is read against it). `cases` reads the rows as
    court opinions. An empty page gives rows == []."""
    doc = _doc(html)
    rows = []
    for row in doc.xpath(f'//div[@id="gs_res_ccl_mid"]/div[{_cls("gs_r")}][.//h3[{_cls("gs_rt")}]]'):
        if row.xpath('.//h4[@class="gs_rt2"]') or "gs_qsuggest_wrap" in (row.get("class") or ""):
            continue
        rows.append(_case_row(row) if cases else _article_row(row))
    starts = [int(s) for href in doc.xpath('//div[@id="gs_n"]//a/@href | //div[@id="gs_nm"]//a/@href | //div[@id="gs_nml"]//a/@href')
              for s in re.findall(r"[?&]start=(\d+)", href)]
    return {
        "total_count": _total(_text(_first(doc, '//div[@id="gs_ab_md"]'))),
        "rows": rows,
        "profiles": [] if cases else _profiles(doc),
        "related_searches": [t for t in (clean(a.text_content()) for a in doc.xpath(f'//div[{_cls("gs_qsuggest")}]//a')) if t],
        "citations_per_year": _history(doc),
        # "Showing the best result for this search. See all results": the site answered one match alone
        "is_best_result": bool(doc.xpath(f'//div[{_cls("gs_res_lnfo")}]//a[contains(@href, "lookup=0")]')),
        "has_next": any(s > start for s in starts),
        "has_pager": bool(starts),
    }


# ---- the cite popup ------------------------------------------------------------------

def parse_cite(html):
    """The cite popup -> {styles: [{style, citation}], exports: {bibtex, endnote, refman, refworks}}."""
    doc = _doc(html)
    styles = []
    for tr in doc.xpath('//div[@id="gs_citt"]//tr'):
        name, text = _text(_first(tr, ".//th")), _text(_first(tr, f'.//div[{_cls("gs_citr")}]'))
        if name and text:
            styles.append({"style": name, "citation": text})
    exports = {(_text(a) or "").lower(): refs.absolute(a.get("href")) for a in doc.xpath('//div[@id="gs_citi"]//a[@href]')}
    return {"styles": styles, "exports": {k: exports.get(k) for k in ("bibtex", "endnote", "refman", "refworks")}}


def parse_suggestions(text):
    """The /scholar_complete JSON -> the suggestions, as the search box
    shows them (an entry written 'x|text' is shown as its text)."""
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return []
    values = payload.get("l") if isinstance(payload, dict) else None
    return [s for s in (clean(str(v).split("|", 1)[-1]) for v in values or []) if s]


# ---- an author's profile -------------------------------------------------------------

def _profile_articles(doc):
    rows = []
    for tr in doc.xpath('//tr[@class="gsc_a_tr"]'):
        a = _first(tr, './/a[@class="gsc_a_at"]')
        if a is None:
            continue
        article = _param(a.get("href"), "citation_for_view")
        greys = tr.xpath('.//div[@class="gs_gray"]')
        publication = None
        if len(greys) > 1:
            year_note = _text(_first(greys[1], './/span[@class="gs_oph"]')) or ""
            publication = clean((_text(greys[1]) or "")[:len(_text(greys[1]) or "") - len(year_note)].rstrip(", ")) if year_note \
                else _text(greys[1])
        cited = _first(tr, f'.//a[{_cls("gsc_a_ac")}]')
        rows.append({
            "id": article,
            "title": _text(a),
            "link": refs.author_article_link(article) if article else None,
            "authors": _split_names(_text(greys[0])) if greys else [],
            "has_more_authors": bool(greys) and "..." in (_text(greys[0]) or ""),
            "publication": publication,
            "year": _year(_text(_first(tr, './/td[@class="gsc_a_y"]'))),
            "cited_by_count": _count(_text(cited)) if cited is not None else None,
            "cited_by_link": refs.cited_by_link(_param(cited.get("href"), "cites")) if cited is not None else None,
        })
    return rows


def parse_author(html, author_id):
    """A profile page -> the author's record with the article rows of the
    page that was asked for (`articles`, `has_more_articles`). A profile
    without citations has no metrics table: its numbers are null."""
    doc = _doc(html)
    contact = _first(doc, '//div[@id="gsc_prf_ivh"]')
    website = next(iter(contact.xpath('.//a[@href][not(starts-with(@href, "/"))]/@href')), None) if contact is not None else None
    contact_text = _text(contact) or ""
    org = _first(doc, '//a[@class="gsc_prf_ila"][contains(@href, "view_org")]')
    photo = next(iter(doc.xpath('//img[@id="gsc_prf_pup-img"]/@src')), None)
    cells = [[_count(_text(td)) for td in tr.xpath('.//td[@class="gsc_rsb_std"]')] for tr in doc.xpath('//table[@id="gsc_rsb_st"]/tbody/tr')]
    cells += [[None, None]] * (3 - len(cells))
    since = _year(_text(_first(doc, '(//table[@id="gsc_rsb_st"]//th)[3]')))

    def metric(row):
        values = (row + [None, None])[:2]
        return {"all": values[0], "recent": values[1]}

    co_authors = []
    for li in doc.xpath('//ul[@class="gsc_rsb_a"]/li'):
        a = _first(li, './/span[@class="gsc_rsb_a_desc"]/a[@href]')
        if a is None:
            continue
        co_id = _param(a.get("href"), "user")
        notes = [_text(s) for s in li.xpath(f'.//span[{_cls("gsc_rsb_a_ext")}]')]
        co_authors.append({"id": co_id, "name": _text(a), "link": refs.author_link(co_id),
                           "affiliation": notes[0] if notes else None,
                           "email_domain": _domain(notes[1]) if len(notes) > 1 else None})
    available = _count(_text(_first(doc, '//div[@class="gsc_rsb_m_a"]/span')))
    not_available = _count(_text(_first(doc, '//div[@class="gsc_rsb_m_na"]/div')))
    more = _first(doc, '//button[@id="gsc_bpf_more"]')
    return {
        "id": author_id,
        "name": _text(_first(doc, '//div[@id="gsc_prf_in"]')),
        "link": refs.author_link(author_id),
        "affiliation": _text(_first(doc, '(//div[@class="gsc_prf_il"])[1]')),
        "organization": {"id": _param(org.get("href"), "org"), "name": _text(org)} if org is not None else None,
        "email_domain": _domain(contact_text.split(" - ")[0]),
        "website": website,
        "interests": [t for t in (_text(a) for a in doc.xpath('//div[@id="gsc_prf_int"]/a')) if t],
        "photo": refs.absolute(photo) if photo and "avatar_scholar" not in photo else None,
        "citations": metric(cells[0]),
        "h_index": metric(cells[1]),
        "i10_index": metric(cells[2]),
        "recent_since_year": since,
        "citations_per_year": _per_year(doc, "gsc_g_t", "gsc_g_a", "gsc_g_al"),
        "public_access": {"available": available, "not_available": not_available}
        if available is not None or not_available is not None else None,
        "co_authors": co_authors,
        "articles": _profile_articles(doc),
        "has_more_articles": more is not None and more.get("disabled") is None,
    }


def parse_co_authors(html):
    """The co-author fragment of a profile -> [{id, name, link, affiliation, email_domain, photo}]."""
    doc = _doc(html)
    out = []
    for box in doc.xpath(f'//div[{_cls("gsc_ucoar")}]'):
        a = _first(box, './/h3[@class="gs_ai_name"]/a')
        co_id = (box.get("id") or "").replace("gsc_ucoar-", "") or (_param(a.get("href"), "user") if a is not None else None)
        photo = next(iter(box.xpath(".//img/@src")), None)
        out.append({"id": co_id, "name": _text(a), "link": refs.author_link(co_id),
                    "affiliation": _text(_first(box, './/div[@class="gs_ai_aff"]')),
                    "email_domain": _domain(_text(_first(box, './/div[@class="gs_ai_eml"]'))),
                    "photo": refs.absolute(photo) if photo and "avatar_scholar" not in photo else None})
    return out


# ---- an article on a profile ---------------------------------------------------------

def _publication_date(text):
    """'2012' -> '2012', '2015/5' -> '2015-05', '2026/11/2' -> '2026-11-02' (as much of the date as the site has)."""
    found = re.match(r"^(\d{4})(?:/(\d{1,2}))?(?:/(\d{1,2}))?$", (text or "").strip())
    if not found:
        return clean(text)
    return "-".join(part.zfill(2) for part in found.groups() if part)


def _article_profile(doc, author_article):
    """The author whose profile the article page belongs to (its sidebar)."""
    author_id = author_article.split(":")[0]
    a = _first(doc, '//div[@id="gsc_sb_ui"]/div/a[contains(@href, "user=")]')
    return {"id": author_id, "name": _text(a), "link": refs.author_link(author_id)}


def parse_article(html, author_article):
    """A "View article" page -> the article's record."""
    doc = _doc(html)
    title_link = _first(doc, '//a[@class="gsc_oci_title_link"]')
    out = {
        "id": author_article,
        "title": _text(_first(doc, '//div[@id="gsc_oci_title"]')),
        "link": refs.author_article_link(author_article),
        "source_link": refs.absolute(title_link.get("href")) if title_link is not None else None,
        "profile": _article_profile(doc, author_article),
        "authors": [],
        "publication_date": None, "journal": None, "conference": None, "book": None, "source": None, "publisher": None,
        "volume": None, "issue": None, "pages": None, "institution": None, "report_number": None,
        "patent_office": None, "patent_number": None, "application_number": None,
        "description": None,
        "cited_by_count": None,
        "cited_by_link": None,
        "citations_per_year": _per_year(doc, "gsc_oci_g_t", "gsc_oci_g_a", "gsc_oci_g_al"),
        "resources": [],
        "scholar_articles": [],
        "other_fields": [],
    }
    for a in doc.xpath('//div[@id="gsc_oci_title_gg"]//a[@href]'):
        if LIBRARY_LINK in (a.get("href") or ""):
            continue                 # the requesting network's library, as in _resources
        tag = clean(" ".join(a.xpath('.//span[@class="gsc_vcd_title_ggt"]/text()')))
        rest = clean((_text(a) or "").replace(tag or "", "", 1)) or ""
        out["resources"].append({"type": tag.strip("[]").lower() if tag else None,
                                 "source": re.sub(r"^from\s+", "", rest) or None, "link": refs.absolute(a.get("href"))})
    for row in doc.xpath('//div[@id="gsc_oci_table"]/div[@class="gs_scl"]'):
        label = (_text(_first(row, './/div[@class="gsc_oci_field"]')) or "")
        value_el = _first(row, './/div[@class="gsc_oci_value"]')
        if value_el is None:
            continue
        key = ARTICLE_FIELDS.get(label.lower())
        if label.lower() == "total citations":
            cited = _first(value_el, './/a[contains(@href, "cites=")]')
            if cited is not None:
                out["cited_by_count"] = _count(_text(cited))
                out["cited_by_link"] = refs.cited_by_link(_param(cited.get("href"), "cites"))
        elif label.lower() == "scholar articles":
            for snippet in value_el.xpath('.//div[@class="gsc_oci_merged_snippet"]'):
                head = _first(snippet, "./div[1]/a")
                number = _param(head.get("href"), "cluster") if head is not None else None
                links = snippet.xpath('.//a[@class="gsc_oms_link"]')
                cited = next((a for a in links if "cites=" in (a.get("href") or "")), None)
                versions = next((a for a in links if "cluster=" in (a.get("href") or "")), None)
                related = next((a for a in links if "q=related:" in (a.get("href") or "")), None)
                out["scholar_articles"].append({
                    "id": refs.number_to_id(number), "cluster_id": number, "title": _text(head),
                    "publication_summary": _text(_first(snippet, "./div[2]")),
                    "cited_by_count": _count(_text(cited)) if cited is not None else None,
                    "versions_count": _count(_text(versions)) if versions is not None else None,
                    "cited_by_link": refs.cited_by_link(number) if cited is not None else None,
                    "versions_link": refs.versions_link(number) if versions is not None else None,
                    "related_link": refs.related_link(refs.number_to_id(number)) if related is not None else None,
                })
        elif key == "authors":
            out["authors"] = _split_names(_text(value_el))
        elif key == "publication_date":
            out["publication_date"] = _publication_date(_text(value_el))
        elif key == "description":
            out["description"] = html_to_text(lxml_html.tostring(value_el, encoding="unicode"))
        elif key:
            out[key] = _text(value_el)
        elif label:
            out["other_fields"].append({"name": label, "value": _text(value_el)})
    return out


# ---- case law ------------------------------------------------------------------------

def parse_case(html, number):
    """An opinion page -> the case's record with the opinion as plain text."""
    doc = _doc(html)
    opinion = _first(doc, '//div[@id="gs_opinion"]')
    title = re.sub(r"\s+-\s+Google Scholar$", "", page_title(html) or "") or None
    court = year = None
    found = re.search(r"\s-\s(.+?)\s((?:1[5-9]|20)\d\d)$", title or "")
    if found:
        court, year = clean(found.group(1)), int(found.group(2))
    centers = [_text(c) for c in opinion.xpath("./center")] if opinion is not None else []
    name = _text(_first(doc, '//*[@id="gsl_case_name"]'))
    cited_cases = len({h.split("case=")[1].split("&")[0] for h in opinion.xpath('.//a[contains(@href, "scholar_case?case=")]/@href')}) \
        if opinion is not None else 0
    how_cited = next(iter(doc.xpath('//div[@id="gs_tbar_lt"]//a[contains(@href, "scholar_case?about=")]/@href')), None)
    return {
        "id": number,
        "title": title,
        "name": name,
        "link": refs.case_link(number),
        "citation": centers[0] if centers else None,
        "docket": next((c for c in centers[1:5] if c and re.match(r"^Nos?\.", c)), None),
        "court": court,
        "year": year,
        "header_lines": [c for c in centers if c],
        "cited_cases_count": cited_cases,
        "cited_by_link": refs.cited_by_link(number),
        "how_cited_link": refs.absolute(how_cited),
        "opinion": html_to_text(lxml_html.tostring(opinion, encoding="unicode")) if opinion is not None else None,
    }


# ---- Scholar Metrics -----------------------------------------------------------------

def parse_publications(html):
    """A top_venues / search_venues page -> {name, rows: [{rank, id, name, link, h5_index, h5_median}]}."""
    doc = _doc(html)
    rows = []
    for tr in doc.xpath('//table[@id="gsc_mvt_table"]//tr[td]'):
        href = next(iter(tr.xpath('.//a[contains(@href, "venue=")]/@href')), None)
        publication_id = _param(href, "venue")
        numbers = [_count(_text(td)) for td in tr.xpath('./td[@class="gsc_mvt_n"]')] + [None, None]
        rows.append({"rank": _count(_text(_first(tr, './td[@class="gsc_mvt_p"]'))), "id": publication_id,
                     "name": _text(_first(tr, './td[@class="gsc_mvt_t"]')), "link": refs.publication_link(publication_id),
                     "h5_index": numbers[0], "h5_median": numbers[1]})
    return {"name": re.sub(r"\s+-\s+Google Scholar Metrics$", "", page_title(html) or "") or None, "rows": rows}


def parse_publication_articles(html, publication_id):
    """A list_hcore page -> the publication's record and 20 of its most cited articles."""
    doc = _doc(html)
    notes = [_text(li) or "" for li in doc.xpath('//ul[@class="gsc_mlhd_list"]/li')]
    index = next((_count(n.split(":", 1)[1]) for n in notes if n.lower().startswith("h5-index")), None)
    median = next((_count(n.split(":", 1)[1]) for n in notes if n.lower().startswith("h5-median")), None)
    rankings = []
    for note in notes:
        found = re.match(r"^#(\d+)\s+(.+)$", note)
        if found:
            rankings.append({"rank": int(found.group(1)), "category": found.group(2)})
    rows = []
    for tr in doc.xpath('//table[@id="gsc_mpat_table"]//tr[td]'):
        a = _first(tr, './/div[@class="gsc_mpat_ttl"]/a')
        number = _param(a.get("href"), "cluster") if a is not None else None
        greys = [_text(g) for g in tr.xpath('.//div[@class="gs_gray"]')] + [None, None]
        rows.append({"id": refs.number_to_id(number), "cluster_id": number,
                     "title": _text(a) if a is not None else _text(_first(tr, './/div[@class="gsc_mpat_ttl"]')),
                     "authors": _split_names(greys[0]), "has_more_authors": "..." in (greys[0] or ""),
                     "publication": greys[1], "year": _year(_text(_first(tr, './td[@class="gsc_mpat_y"]'))),
                     "cited_by_count": _count(_text(_first(tr, './td[@class="gsc_mpat_c"]'))),
                     "versions_link": refs.versions_link(number)})
    following = [b for b in doc.xpath('//button[@aria-label="Next"]') if b.get("disabled") is None]
    return {"id": publication_id, "name": re.sub(r"\s+-\s+Google Scholar Metrics$", "", page_title(html) or "") or None,
            "link": refs.publication_link(publication_id), "h5_index": index, "h5_median": median, "rankings": rankings,
            "rows": rows, "has_next": bool(following) and bool(rows)}
