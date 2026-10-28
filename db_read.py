"""Explicit pagination for small administrative snapshots (PostgREST caps each page)."""


def all_rows(query, page_size=1000):
    rows = []
    offset = 0
    while True:
        page = query.range(offset, offset + page_size - 1).execute().data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size
