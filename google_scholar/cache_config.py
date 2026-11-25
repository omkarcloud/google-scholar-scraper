"""Cache TTL per /google-scholar/* endpoint (cache.py, keyed on the validated
params). Scholar's index moves slowly: citation counts tick up daily, a
ranking barely changes within a day, an opinion and a Scholar Metrics
edition never do. The author endpoints share ONE cached profile page
(api._profile_page), so details + the first page of articles cost one fetch.
"""
from datetime import timedelta

# A relevance-ordered result page: the order and the counts drift over days.
SEARCH_CACHE = timedelta(hours=12)
# The date order exists to show what is new.
SEARCH_BY_DATE_CACHE = timedelta(hours=1)
# Cited-by, versions and related lists of one article.
ARTICLE_LISTS_CACHE = timedelta(hours=12)
# The cite popup: its export links are signed, and how long a signature lives was not measured.
CITE_CACHE = timedelta(hours=1)
# Search-box suggestions.
SUGGESTIONS_CACHE = timedelta(hours=24)
# One profile page (an author's numbers are recomputed by the site every few days).
AUTHOR_CACHE = timedelta(hours=12)
# One article of a profile.
ARTICLE_CACHE = timedelta(hours=24)
# Case law: a result page, and an opinion (which never changes).
CASE_SEARCH_CACHE = timedelta(hours=12)
CASE_CACHE = timedelta(days=7)
# Scholar Metrics is one edition a year.
PUBLICATIONS_CACHE = timedelta(days=7)
