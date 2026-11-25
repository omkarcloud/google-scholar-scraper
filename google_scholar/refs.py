"""Reference resolvers and link builders for /google-scholar/*.

Scholar names one article two ways, and each of its pages wants one of
them: a 12-character id (`pdcI9r5sCJcJ`, in `related:` and `info:` queries
and on every result row) and a number (`10883068066968164261`, in `cites=`
and `cluster=`). They are the same value: the 12 characters are the
base64url of the number's 8 bytes, little-endian, plus the byte 0x09
(checked on three records, 2026-11-24). A case is named the same way. So
every `article` / `case` param takes either form, or any Scholar link that
carries one, and the resolver hands the numbers on.

An author is a 12-character profile id (`JicYPdAAAAAJ`); an article on a
profile is `<author id>:<12 characters>` (the `citation_for_view` of its
"View article" page); a publication of Scholar Metrics is
`<12 characters>.<edition year>` (`H--JoiVp8x8J.2025`).

Resolvers raise ValueError with a message for the caller (schema_fields.RefField).
"""
import base64
import re
from urllib.parse import parse_qs, quote_plus, urlsplit

SITE = "https://scholar.google.com"
HOST_RE = re.compile(r"^scholar\.google\.[a-z.]{2,6}$|^scholar\.googleusercontent\.com$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{12}$")
NUMBER_RE = re.compile(r"^\d{1,20}$")
QUERY_ID_RE = re.compile(r"^(?:related|info|cache):([A-Za-z0-9_-]{12}):")
AUTHOR_ARTICLE_RE = re.compile(r"^([A-Za-z0-9_-]{12}):([A-Za-z0-9_-]{12})$")
PUBLICATION_RE = re.compile(r"^([A-Za-z0-9_-]{12})(?:\.(\d{4}))?$")
MAX_NUMBER = 2 ** 64 - 1


# ---- the two forms of an article / case id ------------------------------------

def id_to_number(text_id):
    """'pdcI9r5sCJcJ' -> '10883068066968164261'; None when it is not such an id."""
    if not isinstance(text_id, str) or not ID_RE.match(text_id):
        return None
    try:
        raw = base64.urlsafe_b64decode(text_id + "====")
    except Exception:
        return None
    if len(raw) != 9 or raw[8] != 9:
        return None
    return str(int.from_bytes(raw[:8], "little")) if any(raw[:8]) else None


def number_to_id(number):
    """'10883068066968164261' -> 'pdcI9r5sCJcJ'; None for anything else."""
    try:
        value = int(number)
    except (TypeError, ValueError):
        return None
    if not 0 < value <= MAX_NUMBER:
        return None
    return base64.urlsafe_b64encode(value.to_bytes(8, "little") + b"\x09").decode().rstrip("=")


def _link_parts(value):
    """(path, {param: first value}) of a Scholar link, or None when `value`
    is not a link. ValueError for a link of another site."""
    text = value.strip()
    if not re.match(r"^(https?://|scholar\.google)", text, re.I):
        return None
    if not text.lower().startswith("http"):
        text = "https://" + text
    parts = urlsplit(text)
    if not HOST_RE.match((parts.hostname or "").lower()):
        raise ValueError("not a scholar.google.com link")
    return parts.path, {k: v[0] for k, v in parse_qs(parts.query).items() if v}


def _numbers(text):
    """'1,2' -> ['1', '2'] when every part is an id number, else None."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if parts and all(NUMBER_RE.match(p) and 0 < int(p) <= MAX_NUMBER for p in parts):
        return parts
    return None


ARTICLE_HELP = ("an article id (pdcI9r5sCJcJ or 10883068066968164261), or a scholar.google.com link that names one "
                "(its \"Cited by\", \"Related articles\" or \"All versions\" link)")


def resolve_article(value):
    """An article given as its 12-character id, its number, several numbers
    joined by commas (a profile's "Cited by" link names every merged copy),
    or a Scholar link carrying one -> the number(s), comma-joined."""
    text = (value or "").strip()
    link = _link_parts(text)
    if link is not None:
        _, params = link
        found = params.get("cites") or params.get("cluster")
        if not found:
            query_id = QUERY_ID_RE.match(params.get("q") or "")
            found = query_id.group(1) if query_id else None
        if not found:
            raise ValueError(f"the link names no article; give {ARTICLE_HELP}")
        text = found
    numbers = _numbers(text)
    if numbers:
        return ",".join(numbers)
    number = id_to_number(text)
    if number:
        return number
    raise ValueError(f"not an article id; give {ARTICLE_HELP}")


def first_number(article):
    return article.split(",")[0]


def article_text_id(article):
    """The 12-character id of a resolved article (its first number)."""
    return number_to_id(first_number(article))


def resolve_author(value):
    """A profile id (JicYPdAAAAAJ) or a profile link -> the id."""
    text = (value or "").strip()
    link = _link_parts(text)
    if link is not None:
        text = link[1].get("user") or ""
        if not text:
            raise ValueError("the link names no author; give a profile id (JicYPdAAAAAJ) or a profile link")
    if ID_RE.match(text):
        return text
    raise ValueError("not an author id; give a profile id (JicYPdAAAAAJ) or a scholar.google.com/citations?user=… link")


def resolve_author_article(value):
    """An article on a profile: '<author id>:<article id>' or its "View
    article" link -> 'author:article'."""
    text = (value or "").strip()
    link = _link_parts(text)
    if link is not None:
        text = link[1].get("citation_for_view") or ""
    if AUTHOR_ARTICLE_RE.match(text):
        return text
    raise ValueError("not a profile article; give <author id>:<article id> (JicYPdAAAAAJ:VN7nJs4JPk0C) or the "
                     "article's link on the author's profile (…view_op=view_citation…citation_for_view=…)")


def resolve_case(value):
    """A case given as its number, its 12-character id or a
    scholar_case link -> the number."""
    text = (value or "").strip()
    link = _link_parts(text)
    if link is not None:
        text = link[1].get("case") or link[1].get("about") or link[1].get("cites") or ""
    if NUMBER_RE.match(text) and 0 < int(text) <= MAX_NUMBER:
        return text
    number = id_to_number(text)
    if number:
        return number
    raise ValueError("not a case id; give the case number (6386252699535531764) or a scholar.google.com/scholar_case link")


def resolve_publication(value):
    """A publication of Scholar Metrics: 'H--JoiVp8x8J.2025', the bare id
    (the current edition is assumed by the caller of this module), or a
    link with `venue=` -> (id, edition year or None) joined as the site
    writes it when the year is known."""
    text = (value or "").strip()
    link = _link_parts(text)
    if link is not None:
        text = link[1].get("venue") or ""
    found = PUBLICATION_RE.match(text)
    if not found:
        raise ValueError("not a publication id; give the id a /google-scholar/publications row carries "
                         "(H--JoiVp8x8J.2025) or its link")
    return text


# ---- links to the site's own pages ---------------------------------------------

def author_link(author_id):
    return f"{SITE}/citations?user={author_id}&hl=en" if author_id else None


def author_article_link(author_article):
    author_id = author_article.split(":")[0]
    return f"{SITE}/citations?view_op=view_citation&hl=en&user={author_id}&citation_for_view={author_article}"


def cited_by_link(number):
    return f"{SITE}/scholar?cites={number}&hl=en" if number else None


def versions_link(number):
    return f"{SITE}/scholar?cluster={number}&hl=en" if number else None


def related_link(text_id):
    return f"{SITE}/scholar?q=related:{text_id}:scholar.google.com/&hl=en" if text_id else None


def case_link(number):
    return f"{SITE}/scholar_case?case={number}&hl=en" if number else None


def publication_link(publication_id):
    return f"{SITE}/citations?hl=en&view_op=list_hcore&venue={publication_id}" if publication_id else None


def search_link(query):
    return f"{SITE}/scholar?hl=en&q={quote_plus(query)}" if query else None


def absolute(href):
    """A link of a Scholar page as an absolute one; None for a script link."""
    if not href or href.startswith("javascript"):
        return None
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return SITE + href
    return href
