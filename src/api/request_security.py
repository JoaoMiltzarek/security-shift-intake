"""Request-level security policy for the loopback-only review cockpit.

The v1 application has no authentication boundary.  Its HTTP policy therefore
keeps every peer on loopback, rejects cross-site state changes, bounds request
bodies and form values, and applies browser hardening headers consistently.
"""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

UNSAFE_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
TRUSTED_HOSTS = ("127.0.0.1", "localhost", "[::1]", "testserver")

MAX_REQUEST_BODY_BYTES = 256 * 1024
MAX_FORM_FIELDS = 600
MAX_FORM_KEY_CHARS = 128
MAX_FORM_VALUE_CHARS = 4_000

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; script-src 'self'; "
        "style-src 'self'; base-uri 'none'; object-src 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # Native same-origin POST forms need a non-opaque Origin so the policy can
    # distinguish them from hostile ``Origin: null`` requests. Draft URLs are
    # still never disclosed to another origin.
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class RequestBodyLimitMiddleware:
    """Bound unsafe request bodies even when Content-Length is absent or false."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in UNSAFE_HTTP_METHODS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except ValueError:
                response = Response("Invalid Content-Length.", status_code=400)
                await response(scope, receive, send)
                return
            if declared_length > self.max_bytes:
                response = Response("Request body too large.", status_code=413)
                await response(scope, receive, send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                response = Response("Request interrupted.", status_code=400)
                await response(scope, receive, send)
                return
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                response = Response("Request body too large.", status_code=413)
                await response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_receive, send)


async def bounded_review_form(request: Request) -> Any:
    """Parse the edit form with finite field, upload and per-value budgets."""
    form = await request.form(
        max_files=0,
        max_fields=MAX_FORM_FIELDS,
        max_part_size=MAX_REQUEST_BODY_BYTES,
    )
    items = list(form.multi_items())
    if len(items) > MAX_FORM_FIELDS:
        raise HTTPException(status_code=422, detail="Review form has too many fields.")
    for key, value in items:
        if (
            not isinstance(value, str)
            or len(str(key)) > MAX_FORM_KEY_CHARS
            or len(value) > MAX_FORM_VALUE_CHARS
        ):
            raise HTTPException(status_code=422, detail="Review form field is too large.")
    return form


def is_loopback_client(host: str) -> bool:
    """Accept OS loopback addresses; ``testclient`` is Starlette's in-memory peer."""
    if host == "testclient":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def same_origin(request: Request, origin: str) -> bool:
    """Compare scheme, host and effective port; reject opaque or malformed origins."""
    if origin == "null":
        return False
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            return False
        origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return False
    request_port = request.url.port or (443 if request.url.scheme == "https" else 80)
    return (
        parsed.scheme == request.url.scheme
        and parsed.hostname.lower() == (request.url.hostname or "").lower()
        and origin_port == request_port
    )


def _apply_security_headers(request: Request, response: Response) -> None:
    for name, value in _SECURITY_HEADERS.items():
        response.headers[name] = value
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"


async def enforce_local_request_policy(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    """Enforce the loopback/origin policy and apply browser response headers."""
    client_host = request.client.host if request.client is not None else ""
    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    origin = request.headers.get("origin")
    if not is_loopback_client(client_host):
        response = Response("Local cockpit only.", status_code=403)
    elif request.method in UNSAFE_HTTP_METHODS and (
        fetch_site == "cross-site" or (origin is not None and not same_origin(request, origin))
    ):
        response = Response("Cross-site state change blocked.", status_code=403)
    else:
        response = await call_next(request)
    _apply_security_headers(request, response)
    return response


def install_request_security(app: FastAPI) -> None:
    """Install the complete request policy in its behaviorally significant order."""
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(TRUSTED_HOSTS),
        www_redirect=False,
    )
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)
    app.middleware("http")(enforce_local_request_policy)
