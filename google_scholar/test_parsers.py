"""Offline tests for the Google Scholar parsers and reference resolvers,
against the raw pages in google_scholar/fixtures/.

    python -m pytest google_scholar/test_parsers.py -q
"""
import gzip
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_scholar import parsers as P, refs  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
JORDAN = "pdcI9r5sCJcJ"
JORDAN_NUMBER = "10883068066968164261"
HINTON = "JicYPdAAAAAJ"


def load(name):
    path = os.path.join(FIXTURES, name)
    if os.path.exists(path + ".gz"):
        with gzip.open(path + ".gz", "rt", encoding="utf-8") as f:
            return f.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def results(name, **kw):
    return P.parse_results(load(name), **kw)


# ---- result pages --------------------------------------------------------------------

def test_search_page_rows_and_extras():
    page = results("search_machine_learning.html")
    assert page["total_count"] == 6030000
    assert len(page["rows"]) == 10 and page["has_next"] is True
    assert page["related_searches"][0] == "machine learning prediction" and len(page["related_searches"]) == 8
    assert page["profiles"] == []
    row = page["rows"][1]
    assert row["id"] == JORDAN and row["cluster_id"] == JORDAN_NUMBER and row["type"] is None
    assert row["title"] == "Machine learning: Trends, perspectives, and prospects"
    assert row["link"] == "https://www.science.org/doi/abs/10.1126/science.aaa8415"
    assert row["authors"] == [
        {"name": "MI Jordan", "id": "yxUduqMAAAAJ", "link": "https://scholar.google.com/citations?user=yxUduqMAAAAJ&hl=en"},
        {"name": "TM Mitchell", "id": "MnfzuPYAAAAJ", "link": "https://scholar.google.com/citations?user=MnfzuPYAAAAJ&hl=en"}]
    assert (row["publication"], row["year"], row["source"]) == ("Science", 2015, "science.org")
    assert row["cited_by_count"] == 16569 and row["versions_count"] == 22
    assert row["resources"] == [{"type": "pdf", "source": "cmu.edu", "link": "http://www.cs.cmu.edu/~tom/pubs/Science-ML-2015.pdf"}]
    assert row["cited_by_link"].endswith(f"cites={JORDAN_NUMBER}&hl=en")
    assert row["related_link"] and row["versions_link"]
    assert "<" not in row["snippet"] and row["snippet"].startswith("Machine learning addresses")
    assert row["abstract"] is None and row["published_ago"] is None
    assert page["is_best_result"] is False and page["citations_per_year"] == []


def test_library_links_are_left_out_of_the_resources():
    """Scholar puts the library of the network a request came from next to the
    PDF ("Full View", "Full-Text @ <a university>"): not the paper's own."""
    page = results("search_with_library_links.html")
    assert len(page["rows"]) == 10
    for row in page["rows"]:
        assert all(r["type"] and "instlink" not in r["link"] for r in row["resources"]), row["resources"]
    assert page["rows"][0]["resources"] == [{"type": "pdf", "source": "acm.org", "link": "https://dl.acm.org/doi/pdf/10.1145/3641289"}]


def test_library_links_are_left_out_of_an_article_page_too():
    html = load("article.html")
    plain = P.parse_article(html, "JicYPdAAAAAJ:VN7nJs4JPk0C")["resources"]
    block = '<div id="gsc_oci_title_gg">'
    assert block in html and len(plain) == 1
    library = ('<div class="gsc_oci_title_ggi"><a href="/scholar?output=instlink&amp;q=info:x:scholar.google.com/'
               '&amp;hl=en&amp;oi=lle">Full View</a></div>')
    assert P.parse_article(html.replace(block, block + library, 1), "JicYPdAAAAAJ:VN7nJs4JPk0C")["resources"] == plain


def test_every_row_has_the_same_keys():
    keys = None
    for name in ("search_machine_learning.html", "search_citation_row.html", "search_sorted_by_date.html",
                 "search_single_result.html", "versions.html", "cited_by.html"):
        for row in results(name)["rows"]:
            keys = keys or list(row)
            assert list(row) == keys, name


def test_book_row_drops_its_tag_from_the_title():
    row = results("search_machine_learning.html")["rows"][0]
    assert (row["type"], row["title"], row["publication"], row["year"]) == ("book", "Machine learning", None, 2021)


def test_second_page_and_past_the_end():
    second = results("search_page_2.html", start=10)
    assert len(second["rows"]) == 10 and second["has_next"] is True
    assert not {r["id"] for r in second["rows"]} & {r["id"] for r in results("search_machine_learning.html")["rows"]}
    past = results("search_past_end.html", start=1000)
    assert past["rows"] == [] and past["has_next"] is False and past["has_pager"] is True


def test_search_without_results():
    page = results("search_no_results.html")
    assert page["rows"] == [] and page["total_count"] is None and page["has_next"] is False and page["profiles"] == []


def test_date_order_rows_carry_an_age_and_no_year():
    row = results("search_sorted_by_date.html")["rows"][0]
    assert row["published_ago"] == "3 days ago" and row["year"] is None and row["cited_by_count"] is None
    assert not row["snippet"].startswith("3 days ago")


def test_citation_only_row():
    row = results("search_citation_row.html")["rows"][0]
    assert row["type"] == "citation" and row["title"] == "Handbook of chemistry and physics"
    assert row["link"] is None and row["versions_count"] is None and row["versions_link"] is None
    assert row["cited_by_count"] == 183 and row["year"] == 2004 and row["source"] == "CRC press, Boca Raton, FL"


def test_patent_rows():
    row = results("search_patent_rows.html")["rows"][0]
    assert row["link"].startswith("https://patents.google.com/patent/") and row["source"] == "Google Patents"
    assert row["has_more_authors"] is True and row["authors"][0]["name"] == "WB Chu" and row["year"] == 2014
    assert row["cached_link"].startswith("https://scholar.googleusercontent.com/scholar?q=cache:")


def test_single_result_layout_carries_the_abstract():
    page = results("search_single_result.html")
    assert len(page["rows"]) == 1 and page["total_count"] is None and page["is_best_result"] is True
    whole = results("search_all_results_of_a_best_match.html")
    assert whole["is_best_result"] is False and len(whole["rows"]) == 10 and whole["total_count"] == 137000
    row = page["rows"][0]
    assert row["title"] == "A mathematical theory of communication" and row["year"] == 1948
    assert row["publication"] == "The Bell system technical journal" and row["cited_by_count"] == 187211
    assert row["abstract"].startswith("The recent development of various methods") and row["abstract"].endswith("information.")


def test_profile_blocks():
    one = results("search_with_profile.html")["profiles"]
    assert one == [{"id": HINTON, "name": "Geoffrey Hinton", "link": refs.author_link(HINTON),
                    "affiliation": "Emeritus Prof. Computer Science, University of Toronto",
                    "email_domain": "cs.toronto.edu", "cited_by_count": 1114646}]
    several = results("search_with_profiles.html")["profiles"]
    assert [p["id"] for p in several] == ["D8VWshQAAAAJ", "8zEIdB8AAAAJ", "nLzOlAwAAAAJ"]
    assert several[1]["name"] == "Wei Zhang, PhD" and several[1]["email_domain"] == "csi.cuny.edu"
    assert several[0]["cited_by_count"] == 237914 and several[0]["affiliation"] is None


def test_french_interface_reads_by_link_not_by_label():
    page = results("search_french_interface.html")
    assert page["total_count"] == 6520000 and len(page["rows"]) == 10
    row = page["rows"][0]
    assert row["type"] == "book" and row["title"] == "Machine learning"
    assert row["cited_by_count"] == 4102 and row["versions_count"] == 7


def test_cited_by_and_its_flaky_deep_page():
    page = results("cited_by.html")
    assert len(page["rows"]) == 10 and page["total_count"] == 7560 and page["has_next"] is True
    history = page["citations_per_year"]                        # the dialog's chart: every year, not the sidebar's four
    assert [h["year"] for h in history] == list(range(2016, 2027))
    assert history[0] == {"year": 2016, "citations": 118} and history[-1] == {"year": 2026, "citations": 2542}
    assert results("cited_by_not_found.html")["citations_per_year"] == []
    empty = results("cited_by_empty_deep_page.html", start=200)
    assert empty["rows"] == [] and empty["has_next"] is True          # the pager goes on: api asks again
    missing = results("cited_by_not_found.html")
    assert missing["rows"] == [] and missing["has_next"] is False and missing["has_pager"] is False


def test_versions_rows_keep_their_own_ids():
    page = results("versions.html")
    assert len(page["rows"]) == 10 and page["total_count"] == 22
    first, second = page["rows"][0], page["rows"][1]
    assert first["id"] == JORDAN and first["cited_by_count"] == 16569
    assert second["id"] == "iu8IOX8REBwJ" and second["cluster_id"] == refs.id_to_number("iu8IOX8REBwJ")
    assert second["source"] == "europepmc.org" and second["cited_by_count"] is None
    assert results("versions_not_found.html")["rows"] == []


def test_related():
    page = results("related.html")
    assert len(page["rows"]) == 10 and page["rows"][0]["type"] == "book"
    assert results("related_not_found.html")["rows"] == []


def test_case_search():
    page = results("case_search.html", cases=True)
    assert page["total_count"] == 363000 and len(page["rows"]) == 10 and page["profiles"] == []
    row = page["rows"][0]
    assert row == {
        "id": "6386252699535531764", "name": "Miranda v. Arizona",
        "link": "https://scholar.google.com/scholar_case?case=6386252699535531764&hl=en",
        "citations": ["384 US 436", "86 S. Ct. 1602", "16 L. Ed. 2d 694"], "court": "Supreme Court", "year": 1966,
        "citation_summary": "384 US 436, 86 S. Ct. 1602, 16 L. Ed. 2d 694 - Supreme Court, 1966 - Google Scholar",
        "snippet": row["snippet"], "cited_by_count": 91958, "versions_count": None,
        "cited_by_link": "https://scholar.google.com/scholar?cites=6386252699535531764&hl=en",
        "how_cited_link": "https://scholar.google.com/scholar_case?about=6386252699535531764&q=miranda+rights&hl=en&as_sdt=2006"}
    assert sum(1 for r in page["rows"] if r["versions_count"]) == 8 and page["rows"][1]["versions_count"] in (2, 3)
    assert "Miranda was not advised" in row["snippet"]
    assert results("case_search_no_results.html", cases=True)["rows"] == []


def test_new_opinions_have_no_reporter_citation_yet():
    rows = results("case_search_sorted_by_date.html", cases=True)["rows"]
    assert len(rows) == 10
    fresh = [r for r in rows if not r["citations"]]
    assert fresh and all(r["court"] and r["court"] != "Google Scholar" and r["year"] for r in rows)
    assert all(not c.isdigit() for r in rows for c in r["citations"])


# ---- cite, suggestions ---------------------------------------------------------------

def test_cite_popup():
    cite = P.parse_cite(load("cite.html"))
    assert [s["style"] for s in cite["styles"]] == ["MLA", "APA", "Chicago", "Harvard", "Vancouver"]
    assert cite["styles"][1]["citation"] == ("Jordan, M. I., & Mitchell, T. M. (2015). Machine learning: Trends, "
                                             "perspectives, and prospects. Science, 349(6245), 255-260.")
    assert set(cite["exports"]) == {"bibtex", "endnote", "refman", "refworks"}
    assert cite["exports"]["bibtex"].startswith("https://scholar.googleusercontent.com/scholar.bib?q=info:pdcI9r5sCJcJ")
    assert "scisig=" in cite["exports"]["refman"]
    assert load("cite.bib").startswith("@article{jordan2015machine,")


def test_cite_of_a_not_found_page_is_empty():
    assert P.parse_cite(load("cite_not_found.html")) == {
        "styles": [], "exports": {"bibtex": None, "endnote": None, "refman": None, "refworks": None}}


def test_suggestions():
    assert P.parse_suggestions(load("suggestions.json"))[:2] == ["machine learning", "machine learning algorithms"]
    assert len(P.parse_suggestions(load("suggestions.json"))) == 10
    assert P.parse_suggestions(load("suggestions_none.json")) == []
    assert P.parse_suggestions('{"l":["ab|abc def"]}') == ["abc def"]
    assert P.parse_suggestions("<html>") == [] and P.parse_suggestions(None) == []


# ---- authors -------------------------------------------------------------------------

def test_author_profile():
    author = P.parse_author(load("author.html"), HINTON)
    assert author["name"] == "Geoffrey Hinton" and author["link"] == refs.author_link(HINTON)
    assert author["affiliation"] == "Emeritus Prof. Computer Science, University of Toronto"
    assert author["organization"] == {"id": "8515235176732148308", "name": "University of Toronto"}
    assert author["email_domain"] == "cs.toronto.edu" and author["website"] == "http://www.cs.toronto.edu/~hinton"
    assert author["interests"][:2] == ["machine learning", "psychology"] and len(author["interests"]) == 5
    assert author["photo"].startswith("https://scholar.googleusercontent.com/citations?view_op=view_photo")
    assert author["citations"] == {"all": 1114646, "recent": 648088}
    assert author["h_index"] == {"all": 196, "recent": 134} and author["i10_index"] == {"all": 554, "recent": 406}
    assert author["recent_since_year"] == 2021
    assert author["citations_per_year"][0] == {"year": 1990, "citations": 3495} and len(author["citations_per_year"]) == 37
    assert author["public_access"] == {"available": 8, "not_available": 1}
    assert len(author["co_authors"]) == 11
    assert author["co_authors"][0] == {
        "id": "m1qAiOUAAAAJ", "name": "Terrence Sejnowski", "link": refs.author_link("m1qAiOUAAAAJ"),
        "affiliation": "Francis Crick Professor, Salk Institute, Distingished Professor, UC San Diego", "email_domain": "salk.edu"}
    assert len(author["articles"]) == 20 and author["has_more_articles"] is True
    assert author["articles"][0] == {
        "id": "JicYPdAAAAAJ:VN7nJs4JPk0C", "title": "Imagenet classification with deep convolutional neural networks",
        "link": refs.author_article_link("JicYPdAAAAAJ:VN7nJs4JPk0C"),
        "authors": ["A Krizhevsky", "I Sutskever", "GE Hinton"], "has_more_authors": False,
        "publication": "Advances in neural information processing systems 25", "year": 2012, "cited_by_count": 203237,
        "cited_by_link": "https://scholar.google.com/scholar?cites=2071317309766942398,1036029811429977192,"
                         "13351982974043817797,1245391189097672202&hl=en"}
    assert author["articles"][1]["publication"] == "Nature 521 (7553), 436-44"


def test_profile_without_citations_has_null_numbers():
    author = P.parse_author(load("author_sparse.html"), "12dNH0MAAAAJ")
    assert author["name"] == "Máté Bence Bollók" and author["website"] is None
    assert author["citations"] == {"all": None, "recent": None} and author["h_index"] == {"all": None, "recent": None}
    assert author["citations_per_year"] == [] and author["public_access"] is None and author["recent_since_year"] is None
    assert len(author["articles"]) == 8 and author["has_more_articles"] is False
    assert all(a["cited_by_count"] is None for a in author["articles"])
    assert len(author["co_authors"]) == 4


def test_author_article_pages():
    second = P.parse_author(load("author_articles_page_2.html"), HINTON)
    assert len(second["articles"]) == 100 and second["has_more_articles"] is True
    past = P.parse_author(load("author_articles_past_end.html"), HINTON)
    assert past["articles"] == [] and past["has_more_articles"] is False and past["name"] == "Geoffrey Hinton"


def test_co_authors():
    found = P.parse_co_authors(load("co_authors.html"))
    assert len(found) == 11
    assert found[0]["id"] == "m1qAiOUAAAAJ" and found[0]["name"] == "Terrence Sejnowski" and found[0]["email_domain"] == "salk.edu"
    assert found[0]["photo"].startswith("https://scholar.googleusercontent.com/citations?view_op=small_photo")
    assert len(P.parse_co_authors(load("co_authors_few.html"))) == 4
    assert P.parse_co_authors("") == []


# ---- an article on a profile ---------------------------------------------------------

def test_article_details():
    article = P.parse_article(load("article.html"), "JicYPdAAAAAJ:VN7nJs4JPk0C")
    assert article["title"] == "Imagenet classification with deep convolutional neural networks"
    assert article["source_link"].startswith("https://proceedings.neurips.cc/paper_files/paper/2012/hash/")
    assert article["profile"] == {"id": HINTON, "name": "Geoffrey Hinton", "link": refs.author_link(HINTON)}
    assert article["authors"] == ["Alex Krizhevsky", "Ilya Sutskever", "Geoffrey E Hinton"]
    assert (article["publication_date"], article["journal"], article["volume"]) == (
        "2012", "Advances in neural information processing systems", "25")
    assert article["description"].startswith("We trained a large, deep convolutional neural network")
    assert article["cited_by_count"] == 203237 and "cites=2071317309766942398," in article["cited_by_link"]
    assert article["citations_per_year"][0] == {"year": 2014, "citations": 989} and len(article["citations_per_year"]) == 13
    assert article["resources"] == [{"type": "pdf", "source": "neurips.cc", "link": article["resources"][0]["link"]}]
    assert len(article["scholar_articles"]) == 4
    assert article["scholar_articles"][0]["cluster_id"] == "2071317309766942398"
    assert article["scholar_articles"][0]["cited_by_count"] == 160993 and article["scholar_articles"][0]["versions_count"] == 81
    assert article["scholar_articles"][0]["related_link"] == refs.related_link("vr7GcR7MvhwJ")
    assert article["other_fields"] == []


def test_sparse_article():
    article = P.parse_article(load("article_sparse.html"), "JicYPdAAAAAJ:WxjA8IQWSGYC")
    assert article["publication_date"] == "2026-11-02" and article["issue"] == "4" and article["volume"] == "3"
    assert article["cited_by_count"] is None and article["citations_per_year"] == [] and article["resources"] == []
    assert article["pages"] is None and article["publisher"] is None
    assert len(article["scholar_articles"]) == 1 and article["scholar_articles"][0]["cited_by_count"] is None


def test_publication_date_forms():
    assert P._publication_date("2015/5") == "2015-05" and P._publication_date("1998") == "1998"
    assert P._publication_date("2026/11/2") == "2026-11-02" and P._publication_date(None) is None


# ---- case law ------------------------------------------------------------------------

def test_case_page():
    case = P.parse_case(load("case.html"), "6386252699535531764")
    assert case["title"] == "Miranda v. Arizona, 384 US 436 - Supreme Court 1966"
    assert (case["court"], case["year"], case["citation"], case["docket"]) == ("Supreme Court", 1966, "384 U.S. 436 (1966)", "No. 759.")
    assert case["name"] == "MIRANDA v. ARIZONA." and case["cited_cases_count"] == 128
    assert case["how_cited_link"] == "https://scholar.google.com/scholar_case?about=6386252699535531764&hl=en&as_sdt=2006"
    assert case["opinion"].startswith("384 U.S. 436 (1966)") and len(case["opinion"]) > 200000 and "<p>" not in case["opinion"]


# ---- Scholar Metrics -----------------------------------------------------------------

def test_publications_of_a_category_and_a_language():
    area = P.parse_publications(load("publications_top_category.html"))
    assert area["name"] == "Engineering & Computer Science" and len(area["rows"]) == 20
    assert area["rows"][0] == {
        "rank": 1, "id": "FXe-a9w0eycJ.2025", "name": "IEEE/CVF Conference on Computer Vision and Pattern Recognition",
        "link": refs.publication_link("FXe-a9w0eycJ.2025"), "h5_index": 450, "h5_median": 702}
    language = P.parse_publications(load("publications_top_language.html"))
    assert language["name"] == "English" and len(language["rows"]) == 100 and language["rows"][0]["name"] == "Nature"
    assert language["rows"][-1]["rank"] == 100


def test_publication_search():
    found = P.parse_publications(load("publications_search.html"))["rows"]
    assert len(found) == 20 and found[1]["name"] == "Nature Communications" and found[1]["h5_index"] == 399
    assert P.parse_publications(load("publications_search_no_results.html"))["rows"] == []


def test_publication_articles():
    page = P.parse_publication_articles(load("publication_articles.html"), "H--JoiVp8x8J.2025")
    assert (page["name"], page["h5_index"], page["h5_median"]) == ("Nature", 490, 784)
    assert page["rankings"][0] == {"rank": 1, "category": "Life Sciences & Earth Sciences"}
    assert len(page["rows"]) == 20 and page["has_next"] is True
    row = page["rows"][0]
    assert row["title"] == "Highly accurate protein structure prediction with AlphaFold" and row["cited_by_count"] == 37792
    assert row["cluster_id"] == "6286436358625670901" and row["id"] == refs.number_to_id("6286436358625670901")
    assert row["year"] == 2021 and row["has_more_authors"] is True and row["authors"][0] == "J Jumper"
    past = P.parse_publication_articles(load("publication_articles_past_end.html"), "H--JoiVp8x8J.2025")
    assert past["rows"] == [] and past["has_next"] is False and past["h5_index"] == 490


# ---- references ----------------------------------------------------------------------

def test_the_two_forms_of_an_id():
    assert refs.id_to_number(JORDAN) == JORDAN_NUMBER and refs.number_to_id(JORDAN_NUMBER) == JORDAN
    assert refs.id_to_number("9N6xkf6GoFgJ") == "6386252699535531764"
    assert refs.id_to_number("AAAAAAAAAAAJ") is None and refs.id_to_number("short") is None and refs.id_to_number(None) is None
    assert refs.number_to_id("0") is None and refs.number_to_id("x") is None and refs.number_to_id(2 ** 64) is None


@pytest.mark.parametrize("given", [
    JORDAN, JORDAN_NUMBER,
    "https://scholar.google.com/scholar?cites=10883068066968164261&as_sdt=2005&sciodt=0,5&hl=en",
    "https://scholar.google.com/scholar?cluster=10883068066968164261&hl=en&as_sdt=0,5",
    "https://scholar.google.com/scholar?q=related:pdcI9r5sCJcJ:scholar.google.com/&scioq=machine+learning&hl=en",
    "scholar.google.co.uk/scholar?q=info:pdcI9r5sCJcJ:scholar.google.com/&output=cite",
])
def test_resolve_article_forms(given):
    assert refs.resolve_article(given) == JORDAN_NUMBER


def test_resolve_article_keeps_every_merged_copy():
    link = "https://scholar.google.com/scholar?oi=bibs&hl=en&cites=2071317309766942398,1036029811429977192"
    assert refs.resolve_article(link) == "2071317309766942398,1036029811429977192"
    assert refs.first_number("2071317309766942398,1036029811429977192") == "2071317309766942398"
    assert refs.article_text_id(JORDAN_NUMBER) == JORDAN


@pytest.mark.parametrize("given", ["", "machine learning", "https://example.com/scholar?cites=1",
                                   "https://scholar.google.com/citations?user=JicYPdAAAAAJ", "AAAAAAAAAAAJ"])
def test_resolve_article_refuses(given):
    with pytest.raises(ValueError):
        refs.resolve_article(given)


def test_resolve_the_other_references():
    assert refs.resolve_author("https://scholar.google.com/citations?user=JicYPdAAAAAJ&hl=en&oi=ao") == HINTON
    assert refs.resolve_author(HINTON) == HINTON
    link = "https://scholar.google.com/citations?view_op=view_citation&hl=en&user=JicYPdAAAAAJ&citation_for_view=JicYPdAAAAAJ:VN7nJs4JPk0C"
    assert refs.resolve_author_article(link) == "JicYPdAAAAAJ:VN7nJs4JPk0C"
    assert refs.resolve_case("https://scholar.google.com/scholar_case?case=6386252699535531764&q=miranda&hl=en") == "6386252699535531764"
    assert refs.resolve_case("9N6xkf6GoFgJ") == "6386252699535531764"
    assert refs.resolve_publication("https://scholar.google.com/citations?hl=en&view_op=list_hcore&venue=H--JoiVp8x8J.2025") == "H--JoiVp8x8J.2025"
    assert refs.resolve_publication("H--JoiVp8x8J") == "H--JoiVp8x8J"
    for resolver, bad in ((refs.resolve_author, "hinton"), (refs.resolve_author_article, HINTON), (refs.resolve_case, "miranda"),
                          (refs.resolve_publication, "nature"), (refs.resolve_author, "https://scholar.google.com/scholar?q=x")):
        with pytest.raises(ValueError):
            resolver(bad)
