"""Google Scholar (google_scholar/fetch.py): the box only EARNS the NID
cookie that carries Scholar's pass; GKE replays it over curl, where every
data call lives.

scholar.google.com sends a visitor it has not seen to
www.google.com/sgsync?url=...&sig=...&sg_fe=scife, a page whose script must
run (plain HTTP cannot); the 302 that follows sets a NID that carries the
pass and leads back to the result page with an `sgst` token. No captcha is
involved. A request with that NID is answered directly; without it every
search, cited-by, versions, cite, article and case page is refused.

Two steps, because a Chrome that asks Scholar for a page through a proxy
exit is sent to the /sorry captcha instead of sgsync (4 of 4 exits,
2026-11-24), while a Safari-profile curl on the same kind of exit gets the
sgsync link (8 of 10 fresh US residential exits, 4 of 4 datacenter):

  1. curl (Safari TLS profile) asks for one search through the exit GKE
     sent and reads the sgsync link from the 302;
  2. a throwaway Chrome opens that link, its script runs, and the moment
     the page has moved on (the address carries `sgst`) the NID is read
     and the browser closes. Where the browser lands next does not matter:
     it ended on /sorry in one mint and on the result page in two, and the
     NID carried the pass each time.

The NID is not bound to the exit, the browser or the user-agent (one minted
in an Indian home Chrome answered from US residential exits, the datacenter
pool and the GKE pod's own IP as a Safari-profile curl, 2026-11-24), so GKE
replays it on its own exit.

Measured 2026-11-24 on a laptop's headed Chrome: 3 of 3 mints through US
residential exits, 7.8 s for the whole mint; 7 of 7 on an Indian home
line's own IP.

What one NID is good for, measured the same day (google_scholar/fetch.py
keeps to it): about 30 minutes (three cookies alive at 26-28 min, dead at
31-32 min), and about 300 calls at 3 a second before every exit answers
/sorry for it; 116 of 150 real pages at one call every 2 s with no decline.
"""
import threading
import time

from browser_worker.types import CookieMint, RecipeError

SCHOLAR = "https://scholar.google.com"
SEARCH = SCHOLAR + "/scholar?hl=en&as_sdt=0%2C5&q=tidal+energy"     # the page step 1 asks for
PASS_COOKIE = "NID"
CURL_PROFILES = ("safari260", "safari18_4", "safari18_0", "safari17_0")   # the newest this box's curl_cffi knows
CURL_TIMEOUT = 20
LINK_TRIES = 2


def _curl_session(proxy):
    from curl_cffi import requests as curl
    last = None
    for profile in CURL_PROFILES:
        try:
            return curl.Session(impersonate=profile, proxies={"http": proxy, "https": proxy} if proxy else None)
        except Exception as e:                # a profile this curl_cffi does not have
            last = e
    raise RecipeError(f"google-scholar: no Safari curl profile on this box ({last})")


def sgsync_link(proxy):
    """The sgsync link Scholar sends an unknown visitor to, asked for over
    curl through `proxy`. RecipeError when this exit is sent to the captcha
    instead (GKE then mints on another exit)."""
    seen = []
    for _ in range(LINK_TRIES):
        sess = _curl_session(proxy)
        try:
            resp = sess.get(SEARCH, allow_redirects=False, timeout=CURL_TIMEOUT)
            location = resp.headers.get("location") or ""
            if "/sgsync" in location:
                return location
            seen.append("captcha" if "/sorry/" in location else f"HTTP {resp.status_code}")
        except Exception as e:
            seen.append(type(e).__name__)
        finally:
            try:
                sess.close()
            except Exception:
                pass
    raise RecipeError(f"google-scholar: no sgsync link on this exit ({', '.join(seen)})")


class GoogleScholar(CookieMint):
    name = "google-scholar"
    headless = False
    variants = {"": SEARCH}
    wait_for_cookie = PASS_COOKIE
    referer = None                    # the link is opened as a typed address, as curl's redirect would be followed
    block_resources = ("image", "font", "media")
    browserforge = False
    require_challenge = False         # the sgsync page is the challenge; there is no marker to wait for
    nav_settle = False                # poll from domcontentloaded: hand the cookie back as soon as the page moved on
    poll = 0.2
    timeout = 30
    ttl_seconds = 25 * 60             # a NID carries the pass for about 30 minutes

    _seed = threading.local()

    def seed_url(self, variant: str) -> str:
        link = getattr(self._seed, "link", None)
        if not link:
            raise RecipeError("google-scholar: mint() asks for the sgsync link first")
        return link

    def mint(self, proxy, variant: str = "") -> dict:
        self._seed.link = sgsync_link(proxy)
        try:
            return super().mint(proxy, variant)
        finally:
            self._seed.link = None

    def passed(self, cookies: dict, driver) -> bool:
        """True once the page has left sgsync for the address that carries
        the `sgst` token: the 302 that led there set the NID with the pass."""
        try:
            url = driver.call(lambda page: page.url) or ""
        except Exception:
            return False
        if "sgst" in url:
            return PASS_COOKIE in cookies
        if "/sorry/" in url:
            raise RecipeError("google-scholar: the sgsync link itself was sent to the captcha on this exit")
        return False

    @staticmethod
    def identity(driver, origin):
        # The page is still navigating (to the result page or to /sorry) when
        # the cookie is read: reading the UA in the middle of it can fail.
        for attempt in range(4):
            try:
                return CookieMint.identity(driver, origin)
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(0.5)


RECIPE = GoogleScholar
