"""Google Scholar transport: plain curl_cffi with Safari's TLS profile on
scholar.google.com's server-rendered pages, carrying a NID cookie that a
real browser earned. No login, no browser here.

The pass. Scholar sends a visitor it has not seen to www.google.com/sgsync,
a page whose script must run; the 302 that follows sets a NID that carries
the pass. Without it every search, cited-by, versions, related, cite,
article and case page is refused on every exit. The NID is minted on the
browser box (recipes/google_scholar.py, about 4 s on the box's own IP, 10 of
10 on 2026-11-25) and kept in an identity_pool.Pool shared by every thread.
It is not bound to the exit, the browser or the user-agent, so it goes out
as the only cookie, under the Safari profile's own headers: the minting
Chrome's user-agent and client hints over this TLS profile were refused on
a residential exit that the cookie alone passed (pod probe 2026-11-25), and
the `chrome` profile is sent to the captcha on every exit.

What one NID is good for (measured 2026-11-24, notes/config/google_scholar.md):
  * about 30 minutes: it is used for GOOGLE_SCHOLAR_NID_MAX_AGE and re-minted
    in the background once a request finds it older than
    GOOGLE_SCHOLAR_NID_REFRESH_AGE;
  * about 300 calls at 3 a second, after which every exit answers /sorry
    for it: it serves GOOGLE_SCHOLAR_NID_USES calls, the next one is minted
    ahead, and GOOGLE_SCHOLAR_NID_REFUSALS refusals in a row replace it.

The exits (config.GOOGLE_SCHOLAR_EXIT, then GOOGLE_SCHOLAR_FALLBACK_EXITS,
one step per try, each try on a fresh exit address). Measured 2026-11-25
with the cookie: the pod's own IP is given the captcha page on the result
pages (it had passed them a day earlier) while the profile, metrics and
case pages still pass; of the clean exit pools, 57 of 60 fresh exits of
the first one gave every surface its real answer, and exits in some
countries are sent back to the script check although the cookie is valid;
a US datacenter exit passes four tries in five, a US residential one three
in four. A refusal is one exit's doing, so the retry rides another. Only
the pod's own IP is one address: when the knob is "direct", a surface it
refused starts on the next exit for GOOGLE_SCHOLAR_EXIT_HOLD seconds.

Case law has exits of its own (config.GOOGLE_SCHOLAR_CASE_EXITS): Scholar
answers it to US addresses only. An exit elsewhere is sent to the sign-in
page on the opinion, and in some countries on the case search too
(2026-11-25), which is an upstream error here and moves the try on.

How Scholar refuses (every form is ScholarBlocked, retried on the next exit):
  302 to /sgsync            the cookie carries no pass (expired): it is replaced
  302 to /sorry, 429, 403   the exit, or a worn-out cookie
  200 `id="gs_captcha_f"`   the captcha inside Scholar's own page
A page that is none of these and lacks the marker of the page asked for is
refused too, so a new form cannot reach a parser as data; so is a case-law
search answered with articles (is_case_law_page).

Upstream surfaces (all GET, HTML unless said):
  RESULTS      /scholar?q= | cites= | cluster= | q=related:<id>:scholar.google.com/
               (as_sdt=2006 / 2003 / 4,<state> = case law), 10 rows a page, start=
  CITE         /scholar?q=info:<id>:scholar.google.com/&output=cite   (404 for an unknown id)
  EXPORT       the signed scholar.googleusercontent.com/scholar.bib link of a cite answer
  SUGGESTIONS  /scholar_complete?q=            JSON {"l": [...]}
  AUTHOR       /citations?user=&cstart=&pagesize=[&view_op=list_works&sortby=]
               (an unknown id is a 302 to the sign-in page)
  CO-AUTHORS   /citations?view_op=list_colleagues&json=&user=
  ARTICLE      /citations?view_op=view_citation&citation_for_view=   (404)
  CASE         /scholar_case?case=             (HTTP 200 with a "404" body for an unknown id)
  PUBLICATIONS /citations?view_op=top_venues&vq= | search_venues&vq= | list_hcore&venue=&cstart=

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  ScholarUpstreamError  transport failure / 5xx / an unexpected answer   retryable
  ScholarBlocked        every refusal above                                     retryable
  ScholarNoPass         a pass the box could not mint (a Blocked: HTTP 502)      not tried again within the call
  ScholarNotFound       404, the sign-in redirect of an unknown author, a "404" body   never retried
"""
import os
import sys
import threading
import time

# Allow direct execution (python google_scholar/fetch.py): flat imports
# resolve like under the server. Idempotent when imported normally.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_client
import config
import egress
import identity_pool
from browser_client import BoxRefused, BoxUnavailable
from google_scholar.refs import SITE
from scraper_errors import Blocked, NotFound, UpstreamError
from scraper_utils import sessions

BOX_SITE = "google-scholar"
PASS_COOKIE = "NID"
TIMEOUT = 20
SESSIONS_PER_THREAD = 4      # one per exit of the ladder

CAPTCHA_MARKER = 'id="gs_captcha_f"'
MISSING_MARKER = "no content found for this URL"     # the body of Scholar's HTTP 200 "404" page

# The marker every real answer of a surface holds (research 2026-11-24).
RESULTS_MARKERS = ('id="gs_res_ccl_mid"',)
CITE_MARKERS = ('id="gs_citt"',)
AUTHOR_MARKERS = ('id="gsc_prf_in"',)
CO_AUTHORS_MARKERS = ('id="gsc_codb_content"', 'id="gsc_codb_data"')
ARTICLE_MARKERS = ('id="gsc_oci_title"',)
CASE_MARKERS = ('id="gs_opinion"',)
PUBLICATIONS_MARKERS = ('id="gsc_mvt_table"', 'id="gsc_mp_"', "gsc_mp_")
PUBLICATION_ARTICLES_MARKERS = ('id="gsc_mpat_table"', "gsc_mlhd_list")


class ScholarUpstreamError(UpstreamError):
    """Transport failure, 5xx or an answer that is not the page asked for — retryable."""


class ScholarBlocked(ScholarUpstreamError, Blocked):
    """A refusal (the sgsync redirect, /sorry, 429, 403, the captcha inside
    a page) or a pass the box could not mint — retryable on the next exit."""


class ScholarNoPass(ScholarBlocked):
    """The box could not mint a pass (it is down, refused, or the mint budget
    is spent). No exit can help, so the call is not tried again."""


class ScholarNotFound(NotFound):
    """The record does not exist — never retried."""


# ---- sessions and the exit ladder ----------------------------------------------------
# One session per exit per request thread; the thread-local holds sessions
# only. The pass goes out as an explicit cookie header and the jar is
# emptied before every call, so nothing a response set rides along.
_local = threading.local()
_holds = {}                  # surface -> monotonic time until which the first exit is skipped
_holds_lock = threading.Lock()


CASE_SURFACES = ("case_results", "case")     # answered to US addresses only


def _ladder(surface=None):
    """The exits of one call, in order. Case law has its own (US) exits; with
    none configured (a run that sends everything through one exit) it rides
    the same ladder as every other surface."""
    main = [config.GOOGLE_SCHOLAR_EXIT or "direct", *(config.GOOGLE_SCHOLAR_FALLBACK_EXITS or ())]
    if surface in CASE_SURFACES:
        return list(config.GOOGLE_SCHOLAR_CASE_EXITS or ()) or main
    return main


def _exit_steps(surface):
    """The exits one call of `surface` walks, one per try: the ladder,
    without its first exit while that one is held for the surface. Read
    once per call, so a hold this call sets does not skip a step of its own."""
    steps = _ladder(surface)
    with _holds_lock:
        held = time.monotonic() < _holds.get(surface, 0.0)
    return steps[1:] if held and len(steps) > 1 else steps


def _exit_for(surface, attempt, steps=None):
    """The exit of try `attempt` (0-based): the last step serves every further try."""
    steps = steps or _exit_steps(surface)
    return steps[min(attempt, len(steps) - 1)]


def _hold_first_exit(surface, exit_name):
    """The server's own IP refused `surface`: its calls start on the next
    exit for a while. Any other exit is a new address on every session, so
    there is nothing to hold."""
    steps = _ladder(surface)
    if exit_name == "direct" and exit_name == steps[0] and len(steps) > 1:
        with _holds_lock:
            _holds[surface] = time.monotonic() + config.GOOGLE_SCHOLAR_EXIT_HOLD


def _session(exit_name):
    return sessions.keyed(sessions.thread_store(_local), exit_name,
                          lambda: egress.exit_session(exit_name, impersonate=config.GOOGLE_SCHOLAR_IMPERSONATE),
                          SESSIONS_PER_THREAD)


def _drop_session(exit_name):
    """Close the thread's session on `exit_name` so the next try there rides a fresh exit."""
    sessions.drop_keyed(sessions.thread_store(_local), exit_name)


# ---- the pass pool -------------------------------------------------------------------

class Pass(identity_pool.Identity):
    """One minted NID (`value`) and the refusals it met in a row."""

    def __init__(self, nid, exit=None, expires_at=None):
        super().__init__(nid, exit=exit, expires_at=expires_at)
        self.refusals = 0
        self.refreshing = False


def _nid_of(ident):
    value = (ident.get("tokens") or {}).get(PASS_COOKIE)
    if not value:
        value = next((c.get("value") for c in ident.get("cookies") or [] if c.get("name") == PASS_COOKIE), None)
    return value or None


def _mint(key, hint):
    """The pool's mint function: the box earns a NID on its own IP (or on
    `hint`, the exit a caller asks for); when its own IP is refused, once
    more through config.GOOGLE_SCHOLAR_MINT_EXIT. Box errors propagate (the
    pool never catches); an answer without the cookie is a BoxRefused."""
    started = time.monotonic()
    proxy = hint
    try:
        ident = browser_client.mint(BOX_SITE, proxy=proxy)
    except BoxRefused:
        if proxy:
            raise
        proxy = egress.exit_proxy(config.GOOGLE_SCHOLAR_MINT_EXIT)
        ident = browser_client.mint(BOX_SITE, proxy=proxy)
    nid = _nid_of(ident)
    if not nid:
        raise BoxRefused("the browser box answered without a NID cookie")
    print(f"google-scholar: pass minted in {time.monotonic() - started:.1f}s"
          + (" through a proxy exit" if proxy else " on the box's own IP"))
    return Pass(nid, exit=proxy, expires_at=time.time() + config.GOOGLE_SCHOLAR_NID_MAX_AGE)


MINT_WAIT = 45        # seconds a caller waits for a mint in flight (4 s on the box's own IP, 12.5 s p95 through an exit)
_passes = identity_pool.Pool(BOX_SITE, _mint, budget=lambda: config.GOOGLE_SCHOLAR_NID_USES,
                             max_age=lambda: config.GOOGLE_SCHOLAR_NID_MAX_AGE,
                             mint_ahead_at=lambda: config.GOOGLE_SCHOLAR_NID_MINT_AHEAD, mint_wait=MINT_WAIT,
                             mints_per_minute=lambda: config.GOOGLE_SCHOLAR_MINTS_PER_MINUTE)
_pass_lock = threading.Lock()       # the refusal count and the refresh flag of every pass


def _get_pass(replace=None):
    try:
        return _passes.get(replace=replace)
    except identity_pool.MintBudgetExceeded as e:
        raise ScholarNoPass(f"google scholar pass: {e}")
    except (BoxUnavailable, BoxRefused) as e:
        raise ScholarNoPass(f"pass mint failed: {type(e).__name__}: {e}")


def _refresh(ident):
    try:
        _passes.get(replace=ident)        # the old pass serves until the new one lands
    except Exception as e:
        print(f"google-scholar: background pass refresh failed: {type(e).__name__}: {e}")


def _refresh_when_old(ident):
    """Start ONE background re-mint for a pass past GOOGLE_SCHOLAR_NID_REFRESH_AGE,
    so the request that finds it expired is not the one that waits."""
    if time.monotonic() - ident.minted_at < config.GOOGLE_SCHOLAR_NID_REFRESH_AGE:
        return
    with _pass_lock:
        if ident.refreshing:
            return
        ident.refreshing = True
    threading.Thread(target=_refresh, args=(ident,), name="google-scholar-pass-refresh", daemon=True).start()


def _pass_for(needs_pass):
    """The pass one request carries: minted when the surface needs one, else
    whatever the pool already holds (no use charged, no mint)."""
    if not needs_pass:
        return _passes.peek()
    ident = _get_pass()
    _refresh_when_old(ident)
    return ident


def _no_pass(ident):
    """Scholar asked the cookie's holder to earn a pass again: replace it now."""
    if ident is not None:
        _passes.retire(ident)


def _refused(ident):
    """One more refusal for this pass; replaced once they come in a row on any exit."""
    if ident is None:
        return
    with _pass_lock:
        ident.refusals += 1
        worn = ident.refusals >= config.GOOGLE_SCHOLAR_NID_REFUSALS
    if worn:
        _passes.retire(ident)


def _served(ident):
    if ident is not None and ident.refusals:
        with _pass_lock:
            ident.refusals = 0


# ---- requests ------------------------------------------------------------------------

def is_case_law_page(text):
    """True unless a case-law result page came back as an ARTICLE search: rows
    without a single link to an opinion (/scholar_case?case=). Scholar does
    that now and then on an exit (2026-11-25: 3 of 53 court-scoped searches
    answered law-review articles, the plain search's 5,360,000 results; the
    same three states answered their own courts when asked again). A page
    without rows (no result, past the end) passes."""
    if "scholar_case?case=" in text:
        return True
    return 'class="gs_ri"' not in text


def _classify(resp, ident, surface, exit_name, label, markers, signin_is_missing, check=None):
    """The body of a real answer; anything else as the site's error. `check`
    is the surface's own test of the page (False: not the page asked for)."""
    status = resp.status_code
    location = resp.headers.get("location") or ""
    if "/sgsync" in location:
        _no_pass(ident)
        raise ScholarBlocked(f"{label}: sent to the sgsync check (the pass is gone)")
    if "accounts.google.com" in location and signin_is_missing:
        raise ScholarNotFound(f"{label} not found")
    text = resp.text or ""
    if "/sorry/" in location or status in (403, 429) or (status == 200 and CAPTCHA_MARKER in text):
        _refused(ident)
        _hold_first_exit(surface, exit_name)
        what = "the captcha page" if status == 200 or "/sorry/" in location else f"HTTP {status}"
        raise ScholarBlocked(f"{label}: {what} on the {exit_name} exit")
    if status == 404 or (status == 200 and MISSING_MARKER in text[-4000:]):
        raise ScholarNotFound(f"{label} not found")
    if status != 200:
        raise ScholarUpstreamError(f"{label}: HTTP {status}" + (f" -> {location[:80]}" if location else ""))
    if markers and not any(marker in text for marker in markers):
        raise ScholarBlocked(f"{label}: not the page asked for ({len(text)} characters) on the {exit_name} exit")
    if check is not None and not check(text):
        raise ScholarBlocked(f"{label}: the site answered another kind of page on the {exit_name} exit")
    _served(ident)
    return text


def _get(url, params=None, *, surface, label, markers=(), needs_pass=True, signin_is_missing=False, cookie=True,
         check=None):
    last = None
    tries = max(1, int(config.GOOGLE_SCHOLAR_TRIES))
    steps = _exit_steps(surface)
    for attempt in range(tries):
        exit_name = _exit_for(surface, attempt, steps)
        started = time.monotonic()
        try:
            ident = _pass_for(needs_pass) if cookie else None
            sess = _session(exit_name)
            try:
                sess.cookies.clear()
            except Exception:
                pass
            headers = {"cookie": f"{PASS_COOKIE}={ident.value}"} if ident is not None else {}
            try:
                resp = sess.get(url, params=params, headers=headers, allow_redirects=False, timeout=TIMEOUT)
            except Exception as e:
                raise ScholarUpstreamError(f"{label}: request failed on the {exit_name} exit after "
                                           f"{time.monotonic() - started:.1f} s: {type(e).__name__}: {str(e)[:120]}")
            return _classify(resp, ident, surface, exit_name, label, markers, signin_is_missing, check)
        except ScholarNoPass:
            raise
        except ScholarUpstreamError as e:
            last = e
            print(f"google-scholar: try {attempt + 1} of {tries} failed: {e}")
            _drop_session(exit_name)
            if attempt + 1 < tries:
                time.sleep(config.GOOGLE_SCHOLAR_RETRY_BACKOFF * (attempt + 1))
    raise last


# ---- the surfaces --------------------------------------------------------------------

def fetch_results(params, label, surface="results"):
    """One result page of /scholar: a search, a cited-by list, the versions
    of an article, its related articles, or a case-law search (surface
    "case_results": a page of articles in its place is refused and asked
    again on the next exit)."""
    return _get(SITE + "/scholar", params, surface=surface, label=label, markers=RESULTS_MARKERS,
                check=is_case_law_page if surface == "case_results" else None)


def fetch_cite(text_id):
    """The cite popup of one article (its five citation styles and the signed
    export links). ScholarNotFound for an id the site does not know."""
    params = {"q": f"info:{text_id}:scholar.google.com/", "output": "cite", "scirp": "0", "hl": "en"}
    return _get(SITE + "/scholar", params, surface="cite", label=f"article {text_id}", markers=CITE_MARKERS)


def fetch_export(link):
    """The text of a signed export link (BibTeX) taken from a cite answer."""
    return _get(link, surface="export", label="the BibTeX export", needs_pass=False, cookie=False)


def fetch_suggestions(query):
    """The search box's suggestions: the raw JSON text."""
    return _get(SITE + "/scholar_complete", {"q": query, "hl": "en", "as_sdt": "0,5"}, surface="suggestions",
                label=f"suggestions for {query!r}", markers=('"l"',), needs_pass=False)


def fetch_author(author_id, cstart=0, pagesize=20, sortby=None):
    """An author's profile page with `pagesize` articles from `cstart`.
    ScholarNotFound for an unknown id (the site answers the sign-in page)."""
    params = {"hl": "en", "user": author_id, "cstart": str(cstart), "pagesize": str(pagesize)}
    if sortby:
        params.update({"view_op": "list_works", "sortby": sortby})
    return _get(SITE + "/citations", params, surface="profile", label=f"author {author_id}", markers=AUTHOR_MARKERS,
                needs_pass=False, signin_is_missing=True)


def fetch_co_authors(author_id):
    """The full co-author list of a profile (the fragment its "View all" loads)."""
    params = {"view_op": "list_colleagues", "hl": "en", "json": "", "user": author_id}
    return _get(SITE + "/citations", params, surface="profile", label=f"author {author_id}",
                markers=CO_AUTHORS_MARKERS, needs_pass=False, signin_is_missing=True)


def fetch_author_article(author_article):
    """The "View article" page of one article on a profile."""
    author_id = author_article.split(":")[0]
    params = {"view_op": "view_citation", "hl": "en", "user": author_id, "citation_for_view": author_article}
    return _get(SITE + "/citations", params, surface="article", label=f"article {author_article}",
                markers=ARTICLE_MARKERS, signin_is_missing=True)


def fetch_case(number):
    """The opinion page of one case."""
    return _get(SITE + "/scholar_case", {"case": number, "hl": "en", "as_sdt": "2006"}, surface="case",
                label=f"case {number}", markers=CASE_MARKERS)


def fetch_publications(vq):
    """Scholar Metrics' top publications of one area, subcategory or language."""
    return _get(SITE + "/citations", {"view_op": "top_venues", "hl": "en", "vq": vq}, surface="metrics",
                label=f"publications of {vq}", markers=PUBLICATIONS_MARKERS, needs_pass=False)


def fetch_publication_search(query):
    """Scholar Metrics' publications matching a name (the site serves 20, no page 2)."""
    return _get(SITE + "/citations", {"hl": "en", "view_op": "search_venues", "vq": query}, surface="metrics",
                label=f"publications named {query!r}", markers=PUBLICATIONS_MARKERS, needs_pass=False)


def fetch_publication_articles(publication_id, cstart=0):
    """The most cited articles of one publication (its h5-core), 20 from `cstart`."""
    params = {"hl": "en", "view_op": "list_hcore", "venue": publication_id, "cstart": str(cstart)}
    return _get(SITE + "/citations", params, surface="metrics", label=f"publication {publication_id}",
                markers=PUBLICATION_ARTICLES_MARKERS, needs_pass=False)
