"""Offline tests for the /google-scholar/* request schemas.

    python -m pytest google_scholar/test_schemas.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_scholar import schemas as S, tables  # noqa: E402
from schema_fields import load_query  # noqa: E402

JORDAN, JORDAN_NUMBER, HINTON = "pdcI9r5sCJcJ", "10883068066968164261", "JicYPdAAAAAJ"


def ok(schema, query):
    data, errors = load_query(schema, query)
    assert errors is None, errors
    return data


def refused(schema, query, field):
    data, errors = load_query(schema, query)
    assert data is None and field in errors["errors"], errors
    return errors["errors"][field][0]


def test_search_defaults():
    data = ok(S.ArticlesSearchSchema, {"query": "  machine   learning "})
    assert data == {"query": "machine learning", "page": 1, "sort": "relevance", "type": "any", "include_patents": False,
                    "include_citations": True, "results_language": None, "language": "en", "title_only": False,
                    "author": None, "publication": None, "exact_phrase": None, "any_words": None, "without_words": None,
                    "year_from": None, "year_to": None, "all_results": False}


def test_search_filters_map_to_the_site_tokens():
    data = ok(S.ArticlesSearchSchema, {"query": "x", "sort": "DATE", "type": "review", "include_patents": "true",
                                       "include_citations": "0", "results_language": "ZH-CN", "language": "pt-br",
                                       "year_from": "2019", "year_to": "2021", "page": "100"})
    assert (data["sort"], data["type"], data["include_patents"], data["include_citations"]) == ("date", "review", True, False)
    assert data["results_language"] == "lang_zh-CN" and data["language"] == "pt-BR"
    assert (data["year_from"], data["year_to"], data["page"]) == (2019, 2021, 100)


def test_all_results_flag():
    assert ok(S.ArticlesSearchSchema, {"query": "x", "all_results": "true"})["all_results"] is True
    refused(S.ArticlesSearchSchema, {"query": "x", "all_results": "all"}, "all_results")


def test_search_needs_something_to_search():
    assert "query" in refused(S.ArticlesSearchSchema, {"author": "hinton"}, "query")
    assert ok(S.ArticlesSearchSchema, {"exact_phrase": "attention is all you need"})["query"] is None
    assert ok(S.ArticlesSearchSchema, {"any_words": "crispr talen"})["any_words"] == "crispr talen"


@pytest.mark.parametrize("query, field", [
    ({"query": "x", "sort": "price"}, "sort"),
    ({"query": "x", "type": "book"}, "type"),
    ({"query": "x", "results_language": "xx"}, "results_language"),
    ({"query": "x", "language": "klingon"}, "language"),
    ({"query": "x", "page": "101"}, "page"),
    ({"query": "x", "page": "0"}, "page"),
    ({"query": "x", "year_from": "2024", "year_to": "2020"}, "year_to"),
    ({"query": "x", "year_from": "12"}, "year_from"),
    ({"query": "x", "year_to": "2200"}, "year_to"),
    ({"query": "x", "include_patents": "maybe"}, "include_patents"),
    ({"query": "x", "num": "20"}, "num"),
])
def test_search_refuses(query, field):
    refused(S.ArticlesSearchSchema, query, field)


@pytest.mark.parametrize("given", [
    JORDAN, JORDAN_NUMBER, "https://scholar.google.com/scholar?cites=10883068066968164261&as_sdt=2005&sciodt=0,5&hl=en",
    "https://scholar.google.com/scholar?q=related:pdcI9r5sCJcJ:scholar.google.com/&hl=en"])
def test_article_param_takes_an_id_or_a_link(given):
    for schema in (S.CitedBySchema, S.ArticlePagesSchema, S.CiteSchema):
        assert ok(schema, {"article": given})["article"] == JORDAN_NUMBER


def test_article_param_refuses_other_things():
    for schema in (S.CitedBySchema, S.ArticlePagesSchema, S.CiteSchema):
        assert "article id" in refused(schema, {"article": "machine learning"}, "article")
        refused(schema, {}, "article")
    refused(S.CitedBySchema, {"article": JORDAN, "sort": "date_everything"}, "sort")
    assert ok(S.CitedBySchema, {"article": JORDAN, "query": "radiology", "sort": "date"})["query"] == "radiology"
    assert ok(S.CiteSchema, {"article": JORDAN, "bibtex": "yes"})["bibtex"] is True


def test_author_params():
    assert ok(S.AuthorSchema, {"author": "https://scholar.google.com/citations?user=JicYPdAAAAAJ&hl=en"}) == {"author": HINTON}
    assert "profile id" in refused(S.AuthorSchema, {"author": "geoffrey hinton"}, "author")
    assert ok(S.AuthorArticlesSchema, {"author": HINTON}) == {"author": HINTON, "page": 1, "sort": ""}
    assert ok(S.AuthorArticlesSchema, {"author": HINTON, "sort": "date", "page": "3"}) == {"author": HINTON, "page": 3, "sort": "pubdate"}
    assert ok(S.AuthorArticlesSchema, {"author": HINTON, "sort": "Title"})["sort"] == "title"
    refused(S.AuthorArticlesSchema, {"author": HINTON, "sort": "newest"}, "sort")
    refused(S.AuthorsSearchSchema, {}, "query")


def test_article_details_param():
    link = "https://scholar.google.com/citations?view_op=view_citation&hl=en&user=JicYPdAAAAAJ&citation_for_view=JicYPdAAAAAJ:VN7nJs4JPk0C"
    assert ok(S.ArticleDetailsSchema, {"article": link}) == {"article": "JicYPdAAAAAJ:VN7nJs4JPk0C"}
    assert ok(S.ArticleDetailsSchema, {"article": "JicYPdAAAAAJ:VN7nJs4JPk0C"})["article"] == "JicYPdAAAAAJ:VN7nJs4JPk0C"
    assert "profile article" in refused(S.ArticleDetailsSchema, {"article": JORDAN}, "article")


def test_case_params():
    assert ok(S.CasesSearchSchema, {"query": "miranda rights"}) == {
        "query": "miranda rights", "courts": "all", "page": 1, "sort": "relevance", "year_from": None, "year_to": None}
    assert ok(S.CasesSearchSchema, {"query": "x", "courts": "New-York"})["courts"] == "new-york"
    assert "texas" in refused(S.CasesSearchSchema, {"query": "x", "courts": "mars"}, "courts")
    assert ok(S.CaseSchema, {"case": "https://scholar.google.com/scholar_case?case=6386252699535531764&hl=en"}) == {"case": "6386252699535531764"}
    refused(S.CaseSchema, {"case": "miranda"}, "case")


def test_publication_params():
    assert ok(S.PublicationsTopSchema, {}) == {"category": None, "language": None}
    assert ok(S.PublicationsTopSchema, {"category": "Artificial-Intelligence"})["category"] == "eng_artificialintelligence"
    assert ok(S.PublicationsTopSchema, {"category": "social-sciences"})["category"] == "soc"
    assert ok(S.PublicationsTopSchema, {"language": "ES"})["language"] == "es"
    refused(S.PublicationsTopSchema, {"category": "astrology"}, "category")
    refused(S.PublicationsTopSchema, {"language": "zh"}, "language")
    assert "not both" in refused(S.PublicationsTopSchema, {"category": "oncology", "language": "es"}, "language")
    assert ok(S.PublicationArticlesSchema, {"publication": "H--JoiVp8x8J.2025", "page": "2"}) == {"publication": "H--JoiVp8x8J.2025", "page": 2}
    refused(S.PublicationArticlesSchema, {"publication": "nature"}, "publication")
    refused(S.PublicationsSearchSchema, {"query": " "}, "query")


def test_every_field_is_described():
    for name in dir(S):
        schema = getattr(S, name)
        if isinstance(schema, type) and issubclass(schema, S.BaseSchema) and schema is not S.BaseSchema and not name.startswith("_"):
            for field_name, field in schema().fields.items():
                assert field.metadata.get("description"), f"{name}.{field_name}"


def test_tables_are_whole():
    assert len(tables.CATEGORIES) == 8 and len(tables.SUBCATEGORIES) == 298 and len(tables.STATE_COURTS) == 51
    assert not set(tables.CATEGORIES) & set(tables.SUBCATEGORIES)
    assert len(set(tables.SUBCATEGORIES.values())) == 298
    assert tables.STATE_COURTS["california"] == 5 and tables.STATE_COURTS["texas"] == 44
