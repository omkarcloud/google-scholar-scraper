"""Offline tests for the Google Scholar transport: how an answer is read
(a page, each refusal form, each not-found form), the exit ladder and its
hold, and the pass pool. No network: sessions and the box are replaced.

    python -m pytest google_scholar/test_fetch.py -q
"""
import gzip
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from browser_client import BoxRefused  # noqa: E402
from google_scholar import fetch as F  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SORRY = "https://www.google.com/sorry/index?continue=https://scholar.google.com/scholar%3Fq%3Dx"
SGSYNC = "https://www.google.com/sgsync?url=https%3A%2F%2Fscholar.google.com%2Fscholar&sig=1_A&sg_fe=scife"
SIGNIN = "https://accounts.google.com/Login?hl=en&continue=https://scholar.google.com/citations%3Fuser%3DAAAAAAAAAAAJ"


def load(name):
    path = os.path.join(FIXTURES, name)
    if os.path.exists(path + ".gz"):
        with gzip.open(path + ".gz", "rt", encoding="utf-8") as f:
            return f.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


class Resp:
    def __init__(self, status=200, text="", location=None):
        self.status_code, self.text = status, text
        self.headers = {"location": location} if location else {}


class Session:
    """Answers queued per exit; records what was sent."""

    def __init__(self, exit_name, script, sent):
        self.exit_name, self.script, self.sent = exit_name, script, sent
        self.cookies = self

    def clear(self):
        pass

    def get(self, url, params=None, headers=None, allow_redirects=None, timeout=None):
        self.sent.append({"exit": self.exit_name, "url": url, "params": params, "headers": dict(headers or {}),
                          "allow_redirects": allow_redirects})
        answer = self.script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def wire(monkeypatch):
    """A scripted upstream: wire(answers) -> the list of requests sent."""
    sent, minted = [], []

    def start(answers, mint=None):
        script = list(answers)
        monkeypatch.setattr(F, "_session", lambda exit_name: Session(exit_name, script, sent))
        monkeypatch.setattr(F, "_drop_session", lambda exit_name: None)

        def box_mint(site, proxy=None, variant=""):
            minted.append(proxy)
            if mint:
                return mint(proxy)
            return {"tokens": {"NID": f"nid-{len(minted)}"}, "cookies": []}
        monkeypatch.setattr(F.browser_client, "mint", box_mint)
        return sent
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_RETRY_BACKOFF", 0)
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_EXIT", "direct")
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_FALLBACK_EXITS", ("datacenter", "us"))
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_TRIES", 5)
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_MINT_EXIT", "http://exit.example:1")
    F._passes.reset()
    F._holds.clear()
    start.minted = minted
    yield start
    F._passes.reset()
    F._holds.clear()


PAGE = load("search_machine_learning.html")


def test_a_real_page_goes_out_with_the_pass_as_its_only_cookie(wire):
    sent = wire([Resp(200, PAGE)])
    assert F.fetch_results({"q": "machine learning", "hl": "en"}, "search") == PAGE
    assert len(sent) == 1 and sent[0]["exit"] == "direct" and sent[0]["allow_redirects"] is False
    assert sent[0]["headers"] == {"cookie": "NID=nid-1"}
    assert sent[0]["url"] == "https://scholar.google.com/scholar" and "num" not in sent[0]["params"]
    assert wire.minted == [None]                  # the box's own IP


def test_one_pass_serves_many_calls(wire):
    sent = wire([Resp(200, PAGE)] * 3)
    for _ in range(3):
        F.fetch_results({"q": "x"}, "search")
    assert wire.minted == [None] and {s["headers"]["cookie"] for s in sent} == {"NID=nid-1"}


@pytest.mark.parametrize("refusal", [
    Resp(302, "", SORRY), Resp(429, load("refused_sorry.html")), Resp(403, "<html>403</html>"),
    Resp(200, load("refused_captcha.html"))])
def test_every_refusal_form_moves_down_the_ladder(wire, refusal):
    sent = wire([refusal, refusal, Resp(200, PAGE)])
    assert F.fetch_results({"q": "x"}, "search") == PAGE
    assert [s["exit"] for s in sent] == ["direct", "datacenter", "us"]
    assert wire.minted == [None]                  # a refusal by an exit does not cost the pass


def test_a_refused_first_exit_is_held_for_that_surface_only(wire):
    sent = wire([Resp(302, "", SORRY), Resp(200, PAGE), Resp(200, PAGE), Resp(200, load("author.html"))])
    F.fetch_results({"q": "x"}, "search")
    F.fetch_results({"q": "y"}, "search")
    F.fetch_author("JicYPdAAAAAJ")
    assert [s["exit"] for s in sent] == ["direct", "datacenter", "datacenter", "direct"]


def test_the_sgsync_redirect_replaces_the_pass(wire):
    sent = wire([Resp(302, "", SGSYNC), Resp(200, PAGE)])
    assert F.fetch_results({"q": "x"}, "search") == PAGE
    assert [s["headers"]["cookie"] for s in sent] == ["NID=nid-1", "NID=nid-2"]
    assert [s["exit"] for s in sent] == ["direct", "datacenter"] and wire.minted == [None, None]


def test_refusals_in_a_row_wear_a_pass_out(wire, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_NID_REFUSALS", 3)
    sent = wire([Resp(302, "", SORRY)] * 3 + [Resp(200, PAGE)])
    assert F.fetch_results({"q": "x"}, "search") == PAGE
    assert [s["headers"]["cookie"] for s in sent] == ["NID=nid-1"] * 3 + ["NID=nid-2"]


def test_a_served_call_clears_the_refusal_count(wire, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_NID_REFUSALS", 3)
    wire([Resp(302, "", SORRY), Resp(302, "", SORRY), Resp(200, PAGE), Resp(302, "", SORRY), Resp(200, PAGE)])
    F.fetch_results({"q": "x"}, "search")
    F.fetch_results({"q": "y"}, "search")
    assert wire.minted == [None]


def test_every_try_refused_is_blocked(wire):
    sent = wire([Resp(302, "", SORRY)] * 5)
    with pytest.raises(F.ScholarBlocked) as e:
        F.fetch_results({"q": "x"}, "search")
    assert "captcha" in str(e.value) and [s["exit"] for s in sent] == ["direct", "datacenter", "us", "us", "us"]


def test_a_page_that_is_not_the_one_asked_for_is_refused(wire):
    wire([Resp(200, load("refused_sgsync.html"))] * 5)
    with pytest.raises(F.ScholarBlocked) as e:
        F.fetch_results({"q": "x"}, "search")
    assert "not the page asked for" in str(e.value)


def test_transport_errors_and_5xx_are_retried(wire):
    sent = wire([ConnectionError("reset"), Resp(503, "busy"), Resp(200, PAGE)])
    assert F.fetch_results({"q": "x"}, "search") == PAGE and len(sent) == 3


def test_not_found_forms_are_final(wire):
    sent = wire([Resp(404, load("cite_not_found.html"))])
    with pytest.raises(F.ScholarNotFound):
        F.fetch_cite("AQAAAAAAAAAJ")
    wire([Resp(200, load("case_not_found.html"))])
    with pytest.raises(F.ScholarNotFound):
        F.fetch_case("1")
    wire([Resp(302, load("author_not_found.html"), SIGNIN)])
    with pytest.raises(F.ScholarNotFound) as e:
        F.fetch_author("AAAAAAAAAAAJ")
    assert "AAAAAAAAAAAJ" in str(e.value)
    wire([Resp(200, load("publication_not_found.html"))])
    with pytest.raises(F.ScholarNotFound):
        F.fetch_publication_articles("AAAAAAAAAAAJ.2025")
    wire([Resp(404, load("article_not_found.html"))])
    with pytest.raises(F.ScholarNotFound):
        F.fetch_author_article("JicYPdAAAAAJ:AAAAAAAAAAAC")
    assert len(sent) == 5                         # one request each: nothing was retried


def test_open_surfaces_mint_nothing_and_carry_a_pass_only_when_one_exists(wire):
    sent = wire([Resp(200, load("author.html")), Resp(200, load("suggestions.json")), Resp(200, PAGE),
                 Resp(200, load("co_authors.html"))])
    F.fetch_author("JicYPdAAAAAJ", 100, 100, "pubdate")
    F.fetch_suggestions("machine lea")
    assert wire.minted == [] and sent[0]["headers"] == {} and sent[1]["headers"] == {}
    assert sent[0]["params"] == {"hl": "en", "user": "JicYPdAAAAAJ", "cstart": "100", "pagesize": "100",
                                 "view_op": "list_works", "sortby": "pubdate"}
    F.fetch_results({"q": "x"}, "search")
    F.fetch_co_authors("JicYPdAAAAAJ")
    assert wire.minted == [None] and sent[3]["headers"] == {"cookie": "NID=nid-1"}


def test_the_export_link_goes_out_without_a_cookie(wire):
    sent = wire([Resp(200, PAGE), Resp(200, load("cite.bib"))])
    F.fetch_results({"q": "x"}, "search")
    assert F.fetch_export("https://scholar.googleusercontent.com/scholar.bib?q=info:x&scisig=y").startswith("@article")
    assert sent[1]["headers"] == {} and sent[1]["url"].startswith("https://scholar.googleusercontent.com/")


def test_the_mint_falls_back_to_a_residential_exit(wire):
    def mint(proxy):
        if proxy is None:
            raise BoxRefused("no sgsync link on this exit")
        return {"cookies": [{"name": "NID", "value": "from-exit"}]}
    sent = wire([Resp(200, PAGE)], mint=mint)
    F.fetch_results({"q": "x"}, "search")
    assert wire.minted == [None, "http://exit.example:1"] and sent[0]["headers"] == {"cookie": "NID=from-exit"}


def test_a_mint_that_fails_is_blocked_not_a_crash(wire):
    def mint(proxy):
        raise BoxRefused("the sgsync link itself was sent to the captcha")
    sent = wire([], mint=mint)
    with pytest.raises(F.ScholarBlocked) as e:
        F.fetch_results({"q": "x"}, "search")
    assert "pass mint failed" in str(e.value) and sent == []
    assert wire.minted == [None, "http://exit.example:1"]         # own IP, then the mint exit: once per call, not once per try


def test_a_box_answer_without_the_cookie_is_refused():
    with pytest.raises(BoxRefused):
        import browser_client
        original = browser_client.mint
        browser_client.mint = lambda site, proxy=None, variant="": {"cookies": [{"name": "GSP", "value": "x"}]}
        try:
            F._mint("", "http://exit.example:1")
        finally:
            browser_client.mint = original


def test_exit_ladder_arithmetic(wire):
    wire([])
    assert [F._exit_for("results", n) for n in range(5)] == ["direct", "datacenter", "us", "us", "us"]
    F._hold_first_exit("results", "datacenter")       # a refusal further down holds nothing
    assert F._exit_for("results", 0) == "direct"
    F._hold_first_exit("results", "direct")
    assert [F._exit_for("results", n) for n in range(3)] == ["datacenter", "us", "us"]
    assert F._exit_for("profile", 0) == "direct"


def test_a_pool_exit_is_tried_twice_and_never_held(wire, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_EXIT", "datacenter:isp")
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_FALLBACK_EXITS", ("datacenter:isp", "datacenter", "us"))
    dropped = []
    sent = wire([Resp(302, "", SORRY), Resp(200, load("refused_captcha.html")), Resp(403, ""), Resp(200, PAGE), Resp(200, PAGE)])
    monkeypatch.setattr(F, "_drop_session", dropped.append)
    assert F.fetch_results({"q": "x"}, "search") == PAGE
    assert [s["exit"] for s in sent] == ["datacenter:isp", "datacenter:isp", "datacenter", "us"]
    assert dropped == ["datacenter:isp", "datacenter:isp", "datacenter"]      # each retry rides a fresh exit address
    F.fetch_results({"q": "y"}, "search")
    assert sent[-1]["exit"] == "datacenter:isp" and F._holds == {}           # the next call starts at the top again


def test_case_law_rides_its_own_us_exits(wire, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_EXIT", "datacenter:isp")
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_CASE_EXITS", ("datacenter", "datacenter", "us"))
    sent = wire([Resp(302, "", SIGNIN), Resp(403, ""), Resp(200, load("case.html")), Resp(200, load("case_search.html")),
                 Resp(200, PAGE)])
    assert "gs_opinion" in F.fetch_case("6386252699535531764")       # a sign-in redirect on a case page is the exit's doing
    F.fetch_results({"q": "miranda rights", "as_sdt": "2006"}, "case search", surface="case_results")
    F.fetch_results({"q": "x"}, "search")
    assert [s["exit"] for s in sent] == ["datacenter", "datacenter", "us", "datacenter", "datacenter:isp"]


def test_case_law_without_exits_of_its_own_rides_the_main_ladder(wire, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_CASE_EXITS", ())
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_FALLBACK_EXITS", ())
    sent = wire([Resp(200, load("case.html"))])
    assert "gs_opinion" in F.fetch_case("6386252699535531764")
    assert [s["exit"] for s in sent] == ["direct"]


def test_a_case_law_search_answered_with_articles_is_asked_again(wire, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_SCHOLAR_CASE_EXITS", ("datacenter", "datacenter", "us"))
    cases = load("case_search.html")
    sent = wire([Resp(200, PAGE), Resp(200, cases)])           # an article search in place of the court opinions
    assert F.fetch_results({"q": "fair use", "as_sdt": "4,18"}, "case search", surface="case_results") == cases
    assert [s["exit"] for s in sent] == ["datacenter", "datacenter"]
    assert F.is_case_law_page(load("case_search_no_results.html")) and F.is_case_law_page(load("case_search_sorted_by_date.html"))
    assert not F.is_case_law_page(PAGE)
    wire([Resp(200, PAGE)])
    assert F.fetch_results({"q": "x"}, "search") == PAGE                        # an article search stays an article search


def test_the_shipped_ladder():
    assert config.GOOGLE_SCHOLAR_EXIT == "datacenter:isp"
    assert config.GOOGLE_SCHOLAR_FALLBACK_EXITS == ("datacenter:isp", "datacenter", "us")
    assert config.GOOGLE_SCHOLAR_TRIES >= 1 + len(config.GOOGLE_SCHOLAR_FALLBACK_EXITS)
    assert config.GOOGLE_SCHOLAR_CASE_EXITS == ("datacenter", "datacenter", "us")       # no exit outside the US
