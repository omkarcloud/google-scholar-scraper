"""Use the scraper straight from Python, no server needed.

    python main.py

Each call validates its params with the same schema the API uses (so the
defaults apply) and returns the same JSON the API does, except that a list
keeps its `pagination` block instead of next / previous links. The results
are written to output/*.json.
"""
import json
import os

from google_scholar import api, schemas
from schema_fields import load_query

os.makedirs("output", exist_ok=True)


def run(schema_cls, impl, **params):
    data, error = load_query(schema_cls, {k: str(v) for k, v in params.items()})
    if error:
        raise ValueError(error)
    return impl(**data)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # 10 papers: title, authors with profile ids, journal, year, citation count, versions, PDF link, snippet
    save("articles_search.json", run(schemas.ArticlesSearchSchema, api.articles_search, query='large language models'))

    # what the search box suggests for the words typed so far
    save("articles_suggestions.json", run(schemas.SuggestionsSchema, api.articles_suggestions, query='large lang'))

    # the papers citing "Attention Is All You Need", 10 a page, with its citations per year
    save("articles_cited_by.json", run(schemas.CitedBySchema, api.articles_cited_by, article='5Gohgn6QFikJ'))
