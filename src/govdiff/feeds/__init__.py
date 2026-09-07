"""Per-feed adapters.

A feed module exposes:

    parse(content: bytes) -> pandas.DataFrame

and, when the publisher indexes its own history:

    list_versions(session=None) -> list[dict]  with keys
        title, date (ISO), url, published (dd/mm/yyyy as printed)
"""
