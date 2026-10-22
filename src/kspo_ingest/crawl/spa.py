"""Hash-router semantics shared by discovery, identity and browser collection.

Only #/ and #!/ are routes; #top/#content remain document anchors.
The document URL and its query are kept separate from the virtual route.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def route_fragment(url: str) -> str:
    fragment = urlsplit(url).fragment
    route = fragment[1:] if fragment.startswith("!/") else fragment
    if not route.startswith("/") or route.startswith("//") or "#" in route:
        return ""
    return fragment


def is_spa_url(url: str) -> bool:
    return bool(route_fragment(url))


def effective_parts(url: str):
    """Path/query the application uses (not the HTTP document path/query)."""
    parts = urlsplit(url)
    fragment = route_fragment(url)
    if not fragment:
        return parts
    route = urlsplit(fragment.removeprefix("!"))
    return parts._replace(path=route.path or "/", query=route.query, fragment="")


def restore_route(original: str, effective_url: str) -> str:
    """Put an edited virtual path/query back inside its original document."""
    if not is_spa_url(original):
        return effective_url
    outer, inner = urlsplit(original), urlsplit(effective_url)
    prefix = "!" if route_fragment(original).startswith("!") else ""
    fragment = prefix + urlunsplit(("", "", inner.path or "/", inner.query, ""))
    return urlunsplit((inner.scheme, inner.netloc, outer.path, outer.query, fragment))
