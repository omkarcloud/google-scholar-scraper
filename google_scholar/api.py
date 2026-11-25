"""The /google-scholar/* endpoint functions (route_glue's route_table calls
them with the schema's loaded kwargs).

Every list of /scholar (a search, cited-by, versions, related, case law) is
one page of 10 through _result_page: it asks again when a deep page comes
back empty although its pager goes on (the site does that: 3 of 4 tries at
start=500, 2026-11-24), and it never sends `num` (num=20 is answered with
the captcha, 15 of 15). A search the site answers with one best match alone
says so (`is_best_result`); `all_results` asks for the whole list, as the
site's own "See all results" link does. The site publishes only "About N results" and
serves at most 1,000 of them, so the pagination block carries `has_next`
and the estimate travels as `total_results_estimate`.

authors/details and the first page of authors/articles slice ONE cached
profile page (the 100 most cited articles ride on it).
"""
import config
from cache import cached_call
from google_scholar import cache_config as ttl
from google_scholar import fetch, parsers, refs, tables
from google_scholar.schemas import AUTHOR_ARTICLES_PER_PAGE, ArticlesSearchSchema, PUBLICATION_ARTICLES_PER_PAGE, RESULTS_PER_PAGE
from scraper_errors import NotFound

DETAILS_ARTICLES = 20        # the articles a profile page itself opens with


# ---- one /scholar result page --------------------------------------------------------

def _result_page(params, page, label, cases=False):
    """The parsed result page `page` for `params`, asked again while it is
    an empty page whose pager says there is more."""
    start = (page - 1) * RESULTS_PER_PAGE
    if start:
        params = {**params, "start": str(start)}
    parsed = None
    for _ in range(max(1, int(config.GOOGLE_SCHOLAR_EMPTY_PAGE_TRIES))):
        parsed = parsers.parse_results(fetch.fetch_results(params, label, surface="case_results" if cases else "results"),
                                       start=start, cases=cases)
        if parsed["rows"] or not parsed["has_next"]:
            break
        print(f"google-scholar: {label}: page {page} came back empty with its pager going on; asked again")
    return parsed


def _pagination(page, parsed):
    return {"page": page, "items_per_page": RESULTS_PER_PAGE, "has_next": bool(parsed["rows"]) and parsed["has_next"],
            "total_pages": None, "total_count": None}


def _years(params, year_from, year_to):
    if year_from:
        params["as_ylo"] = str(year_from)
    if year_to:
        params["as_yhi"] = str(year_to)


# ---- articles/search -----------------------------------------------------------------

def _search_params(query, sort, type, include_patents, include_citations, results_language, language, title_only,
                   author, publication, exact_phrase, any_words, without_words, year_from, year_to, all_results=False):
    params = {"hl": language or "en", "as_sdt": "7" if include_patents else "0,5"}
    if all_results:
        params["lookup"] = "0"       # the link of the site's own "See all results"
    if title_only or author or publication or exact_phrase or any_words or without_words:
        # the site's own advanced form: every box is a param of its own
        params["as_q"] = query or ""
        for name, value in (("as_epq", exact_phrase), ("as_oq", any_words), ("as_eq", without_words),
                            ("as_sauthors", author), ("as_publication", publication)):
            if value:
                params[name] = value
        params["as_occt"] = "title" if title_only else "any"
    else:
        params["q"] = query
    _years(params, year_from, year_to)
    if sort == "date":
        params["scisbd"] = "1"
    elif sort == "date_everything":
        params["scisbd"] = "2"
    if type == "review":
        params["as_rr"] = "1"
    if include_citations is False:
        params["as_vis"] = "1"
    if results_language:
        params["lr"] = results_language
    return params


def _articles_search(query=None, page=1, sort="relevance", type="any", include_patents=False, include_citations=True,
                     results_language=None, language="en", title_only=False, author=None, publication=None,
                     exact_phrase=None, any_words=None, without_words=None, year_from=None, year_to=None,
                     all_results=False):
    params = _search_params(query, sort, type, include_patents, include_citations, results_language, language, title_only,
                            author, publication, exact_phrase, any_words, without_words, year_from, year_to, all_results)
    parsed = _result_page(params, page, f"search {query or exact_phrase or any_words!r}")
    return {
        "query": query,
        "total_results_estimate": parsed["total_count"],
        "is_best_result": parsed["is_best_result"],
        "profiles": parsed["profiles"],
        "related_searches": parsed["related_searches"],
        "results": parsed["rows"],
        "pagination": _pagination(page, parsed),
    }


def _search_ttl(data, result):
    return ttl.SEARCH_BY_DATE_CACHE if (data.get("sort") or "").startswith("date") else ttl.SEARCH_CACHE


def articles_search(**data):
    return cached_call("google-scholar.articles_search", data, _articles_search, _search_ttl)


# ---- articles/cited-by, versions, related --------------------------------------------

def _article_list(article, parsed, page, what):
    if page == 1 and not parsed["rows"]:
        raise NotFound(f"Google Scholar has no {what} for the article {refs.article_text_id(article) or article}: "
                       "the id is unknown to it, or the list is empty")
    return {
        # the cited article's own chart rides on its cited-by page: how many citing articles each year has
        "article": {"id": refs.article_text_id(article), "cluster_id": refs.first_number(article),
                    **({"citations_per_year": parsed["citations_per_year"]} if what == "citing articles" else {})},
        "total_results_estimate": parsed["total_count"],
        "results": parsed["rows"],
        "pagination": _pagination(page, parsed),
    }


def _cited_by(article, query=None, page=1, sort="relevance", language="en", year_from=None, year_to=None):
    params = {"cites": article, "hl": language or "en", "as_sdt": "2005", "sciodt": "0,5"}
    if query:
        params.update({"q": query, "scipsc": "1"})
    _years(params, year_from, year_to)
    if sort == "date":
        params["scisbd"] = "1"
    return _article_list(article, _result_page(params, page, f"the articles citing {article}"), page, "citing articles")


def articles_cited_by(**data):
    return cached_call("google-scholar.cited_by", data, _cited_by,
                       lambda d, r: ttl.SEARCH_BY_DATE_CACHE if d.get("sort") == "date" else ttl.ARTICLE_LISTS_CACHE)


def _versions(article, page=1, language="en"):
    params = {"cluster": refs.first_number(article), "hl": language or "en", "as_sdt": "0,5"}
    return _article_list(article, _result_page(params, page, f"the versions of {article}"), page, "versions")


def articles_versions(**data):
    return cached_call("google-scholar.versions", data, _versions, ttl.ARTICLE_LISTS_CACHE)


def _related(article, page=1, language="en"):
    params = {"q": f"related:{refs.article_text_id(article)}:scholar.google.com/", "hl": language or "en", "as_sdt": "0,5"}
    return _article_list(article, _result_page(params, page, f"the articles related to {article}"), page, "related articles")


def articles_related(**data):
    return cached_call("google-scholar.related", data, _related, ttl.ARTICLE_LISTS_CACHE)


# ---- articles/cite -------------------------------------------------------------------

def _cite(article, bibtex=False):
    text_id = refs.article_text_id(article)
    parsed = parsers.parse_cite(fetch.fetch_cite(text_id))
    entry = None
    if bibtex and parsed["exports"].get("bibtex"):
        entry = (fetch.fetch_export(parsed["exports"]["bibtex"]) or "").strip() or None
    return {
        "id": text_id,
        "cluster_id": refs.first_number(article),
        "citations": parsed["styles"],
        "bibtex": entry,
        "export_links": parsed["exports"],
    }


def articles_cite(**data):
    return cached_call("google-scholar.cite", data, _cite, ttl.CITE_CACHE)


# ---- articles/suggestions ------------------------------------------------------------

def _suggestions(query):
    found = parsers.parse_suggestions(fetch.fetch_suggestions(query))
    return {"query": query, "count": len(found), "suggestions": found}


def articles_suggestions(**data):
    return cached_call("google-scholar.suggestions", data, _suggestions, ttl.SUGGESTIONS_CACHE)


# ---- articles/details ----------------------------------------------------------------

def _article_details(article):
    return parsers.parse_article(fetch.fetch_author_article(article), article)


def articles_details(**data):
    return cached_call("google-scholar.article", data, _article_details, ttl.ARTICLE_CACHE)


# ---- the shared profile page ---------------------------------------------------------

def _fetch_profile(author, start, sort):
    return parsers.parse_author(fetch.fetch_author(author, start, AUTHOR_ARTICLES_PER_PAGE, sort or None), author)


def _profile_page(author, start=0, sort=""):
    return cached_call("google-scholar.profile", {"author": author, "start": start, "sort": sort or ""},
                       _fetch_profile, ttl.AUTHOR_CACHE)


# ---- authors/details -----------------------------------------------------------------

def authors_details(author):
    """Everything the profile page shows: who the author is, the citation
    numbers and their history, the co-authors, and the 20 most cited
    articles (/google-scholar/authors/articles pages through all of them)."""
    record = _profile_page(author)
    out = {key: value for key, value in record.items() if key not in ("articles", "has_more_articles")}
    out["co_authors_count"] = len(record["co_authors"])
    out["articles"] = record["articles"][:DETAILS_ARTICLES]
    out["has_more_articles"] = record["has_more_articles"] or len(record["articles"]) > DETAILS_ARTICLES
    return out


# ---- authors/articles ----------------------------------------------------------------

def authors_articles(author, page=1, sort=""):
    record = _profile_page(author, (page - 1) * AUTHOR_ARTICLES_PER_PAGE, sort or "")
    return {
        "author": {"id": record["id"], "name": record["name"], "link": record["link"]},
        "results": record["articles"],
        "pagination": {"page": page, "items_per_page": AUTHOR_ARTICLES_PER_PAGE,
                       "has_next": bool(record["articles"]) and record["has_more_articles"],
                       "total_pages": None, "total_count": None},
    }


# ---- authors/co-authors --------------------------------------------------------------

def _co_authors(author):
    found = parsers.parse_co_authors(fetch.fetch_co_authors(author))
    return {"author": {"id": author, "link": refs.author_link(author)}, "count": len(found), "results": found}


def authors_co_authors(**data):
    return cached_call("google-scholar.co_authors", data, _co_authors, ttl.AUTHOR_CACHE)


# ---- authors/search ------------------------------------------------------------------

def authors_search(query):
    """The profiles the site shows above the results of a search for a name
    (its own author search asks for a sign-in). Rides the cached page of
    /google-scholar/articles/search for the same words."""
    page = articles_search(**ArticlesSearchSchema().load({"query": query}))     # the key a plain search of these words has
    return {"query": query, "count": len(page["profiles"]), "results": page["profiles"]}


# ---- cases ---------------------------------------------------------------------------

def _cases_search(query, courts="all", page=1, sort="relevance", year_from=None, year_to=None):
    scope = "2006" if courts in (None, "all") else "2003" if courts == "federal" else f"4,{tables.STATE_COURTS[courts]}"
    params = {"q": query, "hl": "en", "as_sdt": scope}
    _years(params, year_from, year_to)
    if sort == "date":
        params["scisbd"] = "2"
    parsed = _result_page(params, page, f"case search {query!r}", cases=True)
    return {
        "query": query,
        "courts": courts or "all",
        "total_results_estimate": parsed["total_count"],
        "results": parsed["rows"],
        "pagination": _pagination(page, parsed),
    }


def cases_search(**data):
    return cached_call("google-scholar.cases_search", data, _cases_search,
                       lambda d, r: ttl.SEARCH_BY_DATE_CACHE if d.get("sort") == "date" else ttl.CASE_SEARCH_CACHE)


def _case_details(case):
    return parsers.parse_case(fetch.fetch_case(case), case)


def cases_details(**data):
    return cached_call("google-scholar.case", data, _case_details, ttl.CASE_CACHE)


# ---- publications (Scholar Metrics) --------------------------------------------------

def _publications_top(category=None, language=None):
    parsed = parsers.parse_publications(fetch.fetch_publications(category or language or "en"))
    return {"category": parsed["name"] if category else None, "language": None if category else (language or "en"),
            "count": len(parsed["rows"]), "results": parsed["rows"]}


def publications_top(**data):
    return cached_call("google-scholar.publications_top", data, _publications_top, ttl.PUBLICATIONS_CACHE)


def _publications_search(query):
    rows = parsers.parse_publications(fetch.fetch_publication_search(query))["rows"]
    return {"query": query, "count": len(rows), "results": rows}


def publications_search(**data):
    return cached_call("google-scholar.publications_search", data, _publications_search, ttl.PUBLICATIONS_CACHE)


def _publication_articles(publication, page=1):
    if "." not in publication:
        publication = f"{publication}.{config.GOOGLE_SCHOLAR_METRICS_EDITION}"
    parsed = parsers.parse_publication_articles(
        fetch.fetch_publication_articles(publication, (page - 1) * PUBLICATION_ARTICLES_PER_PAGE), publication)
    return {
        "publication": {key: parsed[key] for key in ("id", "name", "link", "h5_index", "h5_median", "rankings")},
        "results": parsed["rows"],
        "pagination": {"page": page, "items_per_page": PUBLICATION_ARTICLES_PER_PAGE, "has_next": parsed["has_next"],
                       "total_pages": None, "total_count": None},
    }


def publications_articles(**data):
    return cached_call("google-scholar.publication_articles", data, _publication_articles, ttl.PUBLICATIONS_CACHE)
