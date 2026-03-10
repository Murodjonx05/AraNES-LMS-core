"""HTTP constants shared across the application."""

# RFC 2616 hop-by-hop headers that must not be forwarded by proxies
HOP_BY_HOP_HEADERS = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
})
