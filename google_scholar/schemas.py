"""Marshmallow request schemas for every /google-scholar/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url` / `id` pair):

    article      an article id in either of the site's forms (pdcI9r5sCJcJ
                 or 10883068066968164261), or a Scholar link that names it
                 (its "Cited by", "Related articles" or "All versions" link)
    author       a profile id (JicYPdAAAAAJ) or a profile link
    article (articles/details)   <author id>:<article id>, or the article's
                 "View article" link on the author's profile
    case         a case number or a scholar_case link
    publication  the id a /google-scholar/publications row carries
                 (H--JoiVp8x8J.2025) or its link

The filters are the site's own (google_scholar/tables.py holds every value
the site offers); a value the site would silently ignore is refused here.
"""
from marshmallow import ValidationError, validates_schema

from google_scholar import refs, tables
from schema_fields import BaseSchema, ChoiceField, Flag, PageField, PositiveInt, QueryField, RefField, StrippedString
from scraper_utils.schema import max_length

RESULTS_PER_PAGE = 10
MAX_RESULT_PAGE = 100          # the site serves the first 1,000 results of any list (start=990 is its last page)
AUTHOR_ARTICLES_PER_PAGE = 100
MAX_AUTHOR_PAGE = 50
PUBLICATION_ARTICLES_PER_PAGE = 20
MAX_PUBLICATION_PAGE = 50
FIRST_YEAR, LAST_YEAR = 1000, 2100

SORTS = ["relevance", "date", "date_everything"]


class ArticleRefField(RefField):
    resolver = staticmethod(refs.resolve_article)


class AuthorRefField(RefField):
    resolver = staticmethod(refs.resolve_author)


class AuthorArticleRefField(RefField):
    resolver = staticmethod(refs.resolve_author_article)


class CaseRefField(RefField):
    resolver = staticmethod(refs.resolve_case)


class PublicationRefField(RefField):
    resolver = staticmethod(refs.resolve_publication)


def _year(description):
    return PositiveInt(max_value=LAST_YEAR, metadata={"description": description})


def _page(max_page, per_page):
    return PageField(max_page=max_page, metadata={"description": f"page of the list, {per_page} rows each (1 to {max_page})"})


def _language():
    return ChoiceField(tables.INTERFACE_LANGUAGES, load_default="en", metadata={
        "description": "language of the site's interface, which also sets the order of the results (en by default): "
                       + ", ".join(tables.INTERFACE_LANGUAGES)})


class _Years(BaseSchema):
    year_from = _year("only results published in this year or later")
    year_to = _year("only results published in this year or earlier")

    @validates_schema
    def _years_in_order(self, data, **kwargs):
        for name in ("year_from", "year_to"):
            if data.get(name) is not None and data[name] < FIRST_YEAR:
                raise ValidationError(f"Must be a year between {FIRST_YEAR} and {LAST_YEAR}.", name)
        if data.get("year_from") and data.get("year_to") and data["year_from"] > data["year_to"]:
            raise ValidationError("year_to must not be earlier than year_from.", "year_to")


class ArticlesSearchSchema(_Years):
    query = StrippedString(load_default=None, validate=max_length(300), metadata={
        "description": "words to search for; the site's own operators work (author:\"g hinton\", \"exact phrase\", -word). "
                       "Required unless exact_phrase or any_words is given"})
    page = _page(MAX_RESULT_PAGE, RESULTS_PER_PAGE)
    sort = ChoiceField(SORTS, load_default="relevance", metadata={
        "description": "relevance (default), date (newest first; the site then lists only articles added in the last year, those "
                       "with an abstract) or date_everything (the same, with the articles that have no abstract)"})
    type = ChoiceField(["any", "review"], load_default="any", metadata={"description": "any (default) or review: review articles only"})
    include_patents = Flag(load_default=False, metadata={"description": "also return patents (off by default)"})
    include_citations = Flag(load_default=True, metadata={
        "description": "keep [CITATION] rows, works the site knows only from reference lists (on by default)"})
    results_language = ChoiceField(tables.RESULT_LANGUAGES, metadata={
        "description": "only pages written in this language: " + ", ".join(tables.RESULT_LANGUAGES)})
    language = _language()
    title_only = Flag(load_default=False, metadata={"description": "match the words in the title only"})
    author = StrippedString(load_default=None, validate=max_length(200), metadata={"description": "only articles by this author (\"PJ Hayes\")"})
    publication = StrippedString(load_default=None, validate=max_length(200), metadata={
        "description": "only articles published in this journal or conference (\"Nature\")"})
    exact_phrase = StrippedString(load_default=None, validate=max_length(300), metadata={"description": "an exact phrase the article must hold"})
    any_words = StrippedString(load_default=None, validate=max_length(300), metadata={"description": "words of which the article must hold at least one"})
    without_words = StrippedString(load_default=None, validate=max_length(300), metadata={"description": "words the article must not hold"})
    all_results = Flag(load_default=False, metadata={
        "description": "the site answers a search that names one article (its full title) with that best match alone, "
                       "`is_best_result` true; true asks for the whole list instead"})

    @validates_schema
    def _something_to_search(self, data, **kwargs):
        if not (data.get("query") or data.get("exact_phrase") or data.get("any_words")):
            raise ValidationError("Give query, exact_phrase or any_words.", "query")


class CitedBySchema(_Years):
    article = ArticleRefField(metadata={"description": "the cited article: its id (pdcI9r5sCJcJ or 10883068066968164261) or a Scholar link that names it"})
    query = StrippedString(load_default=None, validate=max_length(300), metadata={"description": "search within the citing articles"})
    page = _page(MAX_RESULT_PAGE, RESULTS_PER_PAGE)
    sort = ChoiceField(["relevance", "date"], load_default="relevance", metadata={"description": "relevance (default) or date (newest first)"})
    language = _language()


class ArticlePagesSchema(BaseSchema):
    article = ArticleRefField(metadata={"description": "the article: its id (pdcI9r5sCJcJ or 10883068066968164261) or a Scholar link that names it"})
    page = _page(MAX_RESULT_PAGE, RESULTS_PER_PAGE)
    language = _language()


class CiteSchema(BaseSchema):
    article = ArticleRefField(metadata={"description": "the article: its id (pdcI9r5sCJcJ or 10883068066968164261) or a Scholar link that names it"})
    bibtex = Flag(load_default=False, metadata={"description": "also return the BibTeX entry (one more request to the site)"})


class SuggestionsSchema(BaseSchema):
    query = QueryField(metadata={"description": "the text typed so far"})


class ArticleDetailsSchema(BaseSchema):
    article = AuthorArticleRefField(metadata={
        "description": "an article on an author's profile: <author id>:<article id> (the id of a /google-scholar/authors/articles "
                       "row), or its \"View article\" link"})


class AuthorSchema(BaseSchema):
    author = AuthorRefField(metadata={"description": "a profile id (JicYPdAAAAAJ) or a scholar.google.com profile link"})


class AuthorArticlesSchema(AuthorSchema):
    page = _page(MAX_AUTHOR_PAGE, AUTHOR_ARTICLES_PER_PAGE)
    sort = ChoiceField({"citations": "", "date": "pubdate", "title": "title"}, load_default="", metadata={
        "description": "citations (most cited first, default), date (newest first) or title"})


class AuthorsSearchSchema(BaseSchema):
    query = QueryField(metadata={"description": "an author's name"})


class CasesSearchSchema(_Years):
    query = QueryField(max_length=300, metadata={"description": "words to search the opinions for"})
    courts = ChoiceField(["all", "federal", *tables.STATE_COURTS], load_default="all", metadata={
        "description": "all (default), federal, or a US state's courts: " + ", ".join(tables.STATE_COURTS)})
    page = _page(MAX_RESULT_PAGE, RESULTS_PER_PAGE)
    sort = ChoiceField(["relevance", "date"], load_default="relevance", metadata={"description": "relevance (default) or date (newest first)"})


class CaseSchema(BaseSchema):
    case = CaseRefField(metadata={"description": "a case number (6386252699535531764) or a scholar.google.com/scholar_case link"})


class PublicationsTopSchema(BaseSchema):
    category = ChoiceField({**tables.CATEGORIES, **tables.SUBCATEGORIES}, metadata={
        "description": "an area (" + ", ".join(tables.CATEGORIES) + ") or one of its subcategories (artificial-intelligence, "
                       "oncology, finance …: the 298 of Scholar Metrics); the area's or subcategory's top 20"})
    language = ChoiceField(tables.PUBLICATION_LANGUAGES, metadata={
        "description": "the top 100 publications in a language: " + ", ".join(tables.PUBLICATION_LANGUAGES) + " (en when no category is given)"})

    @validates_schema
    def _one_ranking(self, data, **kwargs):
        if data.get("category") and data.get("language"):
            raise ValidationError("Give a category or a language, not both: the site ranks categories for English only.", "language")


class PublicationsSearchSchema(BaseSchema):
    query = QueryField(metadata={"description": "words of a journal's or conference's name"})


class PublicationArticlesSchema(BaseSchema):
    publication = PublicationRefField(metadata={"description": "a publication id (H--JoiVp8x8J.2025) or its Scholar Metrics link"})
    page = _page(MAX_PUBLICATION_PAGE, PUBLICATION_ARTICLES_PER_PAGE)
