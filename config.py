"""Configuration for the Google Scholar Scraper. Everything can be set with an environment
variable; the defaults work out of the box.

    PORT                   port the API listens on (default 8000)
    GOOGLE_SCHOLAR_PROXY   a datacenter proxy URL for every request, e.g. http://user:pass@host:port
                           (default: none, requests go out from your own connection, which is
                           fine for light use). For volume, use a datacenter proxy: a US one if you
                           call the case-law endpoints, which Google Scholar answers to US addresses only.

Google Chrome must be installed: the scraper opens it for a few seconds to earn the cookie
Google Scholar asks every new visitor for, then reuses that cookie for about 150 calls.

Everything else below is a plain constant with a working default.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

GOOGLE_SCHOLAR_PROXY = os.environ.get("GOOGLE_SCHOLAR_PROXY") or None


# ---- what the code reads off config: defaults for a direct run ----
GOOGLE_SCHOLAR_CASE_EXITS = ()
GOOGLE_SCHOLAR_EMPTY_PAGE_TRIES = 3
GOOGLE_SCHOLAR_EXIT = GOOGLE_SCHOLAR_PROXY      # the exit every session leaves through: your proxy, or direct
GOOGLE_SCHOLAR_EXIT_HOLD = None
GOOGLE_SCHOLAR_FALLBACK_EXITS = ()
GOOGLE_SCHOLAR_IMPERSONATE = 'safari260'
GOOGLE_SCHOLAR_METRICS_EDITION = '2025'
GOOGLE_SCHOLAR_MINTS_PER_MINUTE = 6
GOOGLE_SCHOLAR_MINT_EXIT = None
GOOGLE_SCHOLAR_NID_MAX_AGE = 25 * 60
GOOGLE_SCHOLAR_NID_MINT_AHEAD = 30
GOOGLE_SCHOLAR_NID_REFRESH_AGE = 20 * 60
GOOGLE_SCHOLAR_NID_REFUSALS = 6
GOOGLE_SCHOLAR_NID_USES = 150
GOOGLE_SCHOLAR_RETRY_BACKOFF = 0.3
GOOGLE_SCHOLAR_TRIES = 5
MAX_RETRIES = 3
RETRY_BACKOFF = 2
def burst_slots(share):
    return share


def exit_geo(proxy, timeout=12):
    """Geo of a proxy's exit IP, looked up THROUGH the proxy (ip-api.com, free
    tier, keyed per exit IP so the quota is never shared). Returns the dict
    {countryCode, regionName, city, timezone, query, proxy, hosting} or None
    on any failure — callers keep their configured/system timezone then.
    `proxy` / `hosting` are ip-api's flags for a known proxy address and for
    a server network (exit_pools.py reads them)."""
    try:
        import requests
        r = requests.get(
            "http://ip-api.com/json/?fields=status,countryCode,regionName,city,timezone,query,proxy,hosting",
            proxies={"http": proxy, "https": proxy}, timeout=timeout)
        d = r.json()
        if d.get("status") == "success" and d.get("timezone"):
            return d
    except Exception:
        pass
    return None

