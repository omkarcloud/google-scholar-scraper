"""Offline tests for the /google-scholar/* endpoint functions: what goes
upstream for each filter, the empty deep page that is asked again, the 404
of an unknown article, and the profile page two endpoints share. The fetch
layer and the cache are replaced; the pages are the fixtures.

    python -m pytest google_scholar/test_api.py -q
"""
import gzip
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from google_scholar import api, fetch  # noqa: E402
from google_scholar.schemas import ArticlesSearchSchema  # noqa: E402
from scraper_errors import NotFound  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
JORDAN_NUMBER = "10883068066968164261"
HINTON = "JicYPdAAAAAJ"


def load(name):
    path = os.path.join(FIXTURES, name)
    if os.path.exists(path + ".gz"):
        with gzip.open(path + ".gz", "rt", encoding="utf-8") as f:
            return f.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def upstream(monkeypatch):
    """serve(pages) -> the list of (params, surface) asked for; no cache."""
    calls = []
    monkeypatch.setattr(api, "cached_call", lambda namespace, data, fn, ttl: fn(**data))

    def serve(pages):
        queue = list(pages)

        def fetch_results(params, label, surface="results"):
            calls.append((dict(params), surface))
            return load(queue.pop(0))
        monkeypatch.setattr(fetch, "fetch_results", fetch_results)
        return calls
    return serve


def search(**given):
    return api.articles_search(**ArticlesSearchSchema().load(given))


def test_plain_search_sends_only_what_was_asked(upstream):
    calls = upstream(["search_machine_learning.html"])
    answer = search(query="machine learning")
    assert calls == [({"hl": "en", "as_sdt": "0,5", "q": "machine learning"}, "results")]
    assert list(answer) == ["query", "total_results_estimate", "is_best_result", "profiles", "related_searches", "results",
                            "pagination"]
    assert answer["is_best_result"] is False
    assert answer["total_results_estimate"] == 6030000 and len(answer["results"]) == 10
    assert answer["pagination"] == {"page": 1, "items_per_page": 10, "has_next": True, "total_pages": None, "total_count": None}


def test_every_filter_becomes_the_site_token(upstream):
    calls = upstream(["search_page_2.html"])
    search(query="x", page="2", sort="date", type="review", include_patents="true", include_citations="false",
           results_language="fr", language="de", year_from="2019", year_to="2021")
    assert calls[0][0] == {"hl": "de", "as_sdt": "7", "q": "x", "as_ylo": "2019", "as_yhi": "2021", "scisbd": "1",
                           "as_rr": "1", "as_vis": "1", "lr": "lang_fr", "start": "10"}
    calls.clear()
    upstream(["search_machine_learning.html"])
    search(query="x", sort="date_everything")
    assert calls[0][0]["scisbd"] == "2" and "num" not in calls[0][0]


def test_advanced_boxes_ride_the_site_form(upstream):
    calls = upstream(["search_machine_learning.html", "search_machine_learning.html"])
    search(query="transformer", title_only="true", author="vaswani", without_words="power")
    assert calls[0][0] == {"hl": "en", "as_sdt": "0,5", "as_q": "transformer", "as_eq": "power", "as_sauthors": "vaswani",
                           "as_occt": "title"}
    search(exact_phrase="attention is all you need", any_words="bert gpt", publication="nature")
    assert calls[1][0] == {"hl": "en", "as_sdt": "0,5", "as_q": "", "as_epq": "attention is all you need",
                           "as_oq": "bert gpt", "as_publication": "nature", "as_occt": "any"}


def test_a_best_match_says_so_and_all_results_asks_for_the_list(upstream):
    calls = upstream(["search_single_result.html", "search_all_results_of_a_best_match.html"])
    best = search(query="shannon mathematical theory of communication 1948")
    assert best["is_best_result"] is True and len(best["results"]) == 1 and best["pagination"]["has_next"] is False
    assert "lookup" not in calls[0][0]
    whole = search(query="shannon mathematical theory of communication 1948", all_results="true")
    assert calls[1][0] == {"hl": "en", "as_sdt": "0,5", "lookup": "0", "q": "shannon mathematical theory of communication 1948"}
    assert whole["is_best_result"] is False and len(whole["results"]) == 10 and whole["total_results_estimate"] == 137000
    assert whole["results"][0]["id"] == best["results"][0]["id"]


def test_an_empty_search_is_an_empty_page(upstream):
    calls = upstream(["search_no_results.html"])
    answer = search(query="zxqvjkwpfh")
    assert answer["results"] == [] and answer["pagination"]["has_next"] is False and len(calls) == 1


def test_an_empty_deep_page_is_asked_again(upstream):
    calls = upstream(["cited_by_empty_deep_page.html", "cited_by_empty_deep_page.html", "cited_by.html"])
    answer = api.articles_cited_by(article=JORDAN_NUMBER, page=21)
    assert len(calls) == 3 and all(c[0]["start"] == "200" for c in calls) and len(answer["results"]) == 10


def test_an_empty_deep_page_stays_empty_after_the_tries(upstream, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_EMPTY_PAGE_TRIES", 2)
    calls = upstream(["cited_by_empty_deep_page.html"] * 2)
    answer = api.articles_cited_by(article=JORDAN_NUMBER, page=21)
    assert len(calls) == 2 and answer["results"] == [] and answer["pagination"]["has_next"] is False


def test_a_page_past_the_end_is_not_asked_again(upstream):
    calls = upstream(["search_past_end.html"])
    answer = search(query="machine learning", page="100")
    assert len(calls) == 1 and calls[0][0]["start"] == "990" and answer["results"] == []


def test_cited_by_params_and_shape(upstream):
    calls = upstream(["cited_by.html"])
    answer = api.articles_cited_by(article=JORDAN_NUMBER, query="radiology", sort="date", language="en", year_from=2022, year_to=None)
    assert calls[0][0] == {"cites": JORDAN_NUMBER, "hl": "en", "as_sdt": "2005", "sciodt": "0,5", "q": "radiology",
                           "scipsc": "1", "as_ylo": "2022", "scisbd": "1"}
    assert list(answer) == ["article", "total_results_estimate", "results", "pagination"]
    assert list(answer["article"]) == ["id", "cluster_id", "citations_per_year"]
    assert (answer["article"]["id"], answer["article"]["cluster_id"]) == ("pdcI9r5sCJcJ", JORDAN_NUMBER)
    history = answer["article"]["citations_per_year"]
    assert history[0] == {"year": 2016, "citations": 118} and len(history) == 11


def test_versions_and_related_name_the_article_the_way_each_page_wants(upstream):
    calls = upstream(["versions.html", "related.html"])
    versions = api.articles_versions(article=JORDAN_NUMBER)
    api.articles_related(article=JORDAN_NUMBER, page=2)
    assert calls[0][0] == {"cluster": JORDAN_NUMBER, "hl": "en", "as_sdt": "0,5"}
    assert list(versions) == ["article", "total_results_estimate", "results", "pagination"]
    assert versions["article"] == {"id": "pdcI9r5sCJcJ", "cluster_id": JORDAN_NUMBER}
    assert calls[1][0] == {"q": "related:pdcI9r5sCJcJ:scholar.google.com/", "hl": "en", "as_sdt": "0,5", "start": "10"}


@pytest.mark.parametrize("call, page", [(api.articles_cited_by, "cited_by_not_found.html"),
                                        (api.articles_versions, "versions_not_found.html"),
                                        (api.articles_related, "related_not_found.html")])
def test_an_unknown_article_is_a_404(upstream, call, page):
    upstream([page])
    with pytest.raises(NotFound) as e:
        call(article="1")
    assert "AQAAAAAAAAAJ" in str(e.value)


def test_case_search_scopes(upstream):
    calls = upstream(["case_search.html"] * 3)
    answer = api.cases_search(query="miranda rights")
    api.cases_search(query="miranda rights", courts="federal", sort="date", year_from=2020)
    api.cases_search(query="miranda rights", courts="texas", page=3)
    assert [c[0]["as_sdt"] for c in calls] == ["2006", "2003", "4,44"] and {c[1] for c in calls} == {"case_results"}
    assert calls[1][0]["scisbd"] == "2" and calls[1][0]["as_ylo"] == "2020" and calls[2][0]["start"] == "20"
    assert answer["courts"] == "all" and answer["results"][0]["name"] == "Miranda v. Arizona"


def test_author_search_is_the_profile_block_of_a_search(upstream):
    calls = upstream(["search_with_profiles.html"])
    answer = api.authors_search("wei zhang")
    assert calls[0][0] == {"hl": "en", "as_sdt": "0,5", "q": "wei zhang"}
    assert answer["count"] == 3 and answer["results"][0]["id"] == "D8VWshQAAAAJ"


def test_details_and_articles_share_the_profile_page(monkeypatch):
    asked = []
    store = {}

    def cached(namespace, data, fn, ttl):
        key = (namespace, tuple(sorted(data.items())))
        if key not in store:
            store[key] = fn(**data)
        return store[key]

    def fetch_author(author, cstart=0, pagesize=20, sortby=None):
        asked.append((author, cstart, pagesize, sortby))
        return load("author_articles_page_2.html" if cstart or sortby else "author.html")
    monkeypatch.setattr(api, "cached_call", cached)
    monkeypatch.setattr(fetch, "fetch_author", fetch_author)
    details = api.authors_details(HINTON)
    first = api.authors_articles(HINTON)
    assert asked == [(HINTON, 0, 100, None)]                    # one fetch for both
    assert details["name"] == "Geoffrey Hinton" and details["website"] == "http://www.cs.toronto.edu/~hinton"
    assert len(details["articles"]) == 20 and details["co_authors_count"] == 11 and details["has_more_articles"] is True
    assert first["author"] == {"id": HINTON, "name": "Geoffrey Hinton", "link": details["link"]}
    assert first["pagination"] == {"page": 1, "items_per_page": 100, "has_next": True, "total_pages": None, "total_count": None}
    second = api.authors_articles(HINTON, page=2, sort="pubdate")
    assert asked[-1] == (HINTON, 100, 100, "pubdate") and len(second["results"]) == 100


def test_cite_fetches_the_bibtex_only_when_asked(monkeypatch):
    exported = []
    monkeypatch.setattr(api, "cached_call", lambda namespace, data, fn, ttl: fn(**data))
    monkeypatch.setattr(fetch, "fetch_cite", lambda text_id: load("cite.html"))
    monkeypatch.setattr(fetch, "fetch_export", lambda link: exported.append(link) or load("cite.bib"))
    plain = api.articles_cite(article=JORDAN_NUMBER, bibtex=False)
    assert exported == [] and plain["bibtex"] is None and len(plain["citations"]) == 5 and plain["id"] == "pdcI9r5sCJcJ"
    full = api.articles_cite(article=JORDAN_NUMBER, bibtex=True)
    assert exported == [plain["export_links"]["bibtex"]] and full["bibtex"].startswith("@article{jordan2015machine,")
    assert full["bibtex"].endswith("}")


def test_publication_id_without_an_edition_gets_the_current_one(monkeypatch):
    asked = []
    monkeypatch.setattr(api, "cached_call", lambda namespace, data, fn, ttl: fn(**data))
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_METRICS_EDITION", "2025")
    monkeypatch.setattr(fetch, "fetch_publication_articles",
                        lambda publication, cstart=0: asked.append((publication, cstart)) or load("publication_articles.html"))
    answer = api.publications_articles(publication="H--JoiVp8x8J", page=3)
    assert asked == [("H--JoiVp8x8J.2025", 40)] and answer["publication"]["name"] == "Nature"
    assert answer["pagination"]["has_next"] is True and len(answer["results"]) == 20


def test_top_publications_default_to_english(monkeypatch):
    asked = []
    monkeypatch.setattr(api, "cached_call", lambda namespace, data, fn, ttl: fn(**data))
    monkeypatch.setattr(fetch, "fetch_publications", lambda vq: asked.append(vq) or load(
        "publications_top_category.html" if vq == "eng" else "publications_top_language.html"))
    top = api.publications_top(category=None, language=None)
    area = api.publications_top(category="eng", language=None)
    assert asked == ["en", "eng"] and (top["language"], top["category"], top["count"]) == ("en", None, 100)
    assert (area["language"], area["category"], area["count"]) == (None, "Engineering & Computer Science", 20)
