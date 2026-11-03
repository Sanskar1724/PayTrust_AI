"""Outbound-URL safety for agent callbacks (SSRF protection).

Agents choose where PayTrust POSTs approval outcomes, so a callback URL must never let
them reach PayTrust's own network: localhost, private ranges, link-local cloud metadata
(169.254.169.254), and so on.

Two layers:
  * `check_callback_url` runs when a URL is accepted (request schemas). It rejects bad
    schemes, embedded credentials and literal private hosts.
  * `pin_public_address` runs right before each delivery. It resolves the host, refuses
    if ANY address is non-public, and returns one vetted IP. The caller connects to that
    IP directly, so a DNS answer that changes between check and connect (DNS rebinding)
    cannot redirect the request.

Set CALLBACK_ALLOW_PRIVATE_NETWORKS=true only for local development, where the agent
under test really listens on localhost.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.config import get_settings

_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")


class UnsafeUrl(ValueError):
    """The URL points somewhere PayTrust must not send requests."""


@dataclass(frozen=True)
class PinnedUrl:
    url: str        # same URL with the host replaced by the vetted IP
    host: str       # original hostname, sent as the Host header and TLS SNI
    host_header: str


def _private_allowed() -> bool:
    return get_settings().CALLBACK_ALLOW_PRIVATE_NETWORKS


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])  # drop an IPv6 zone id
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_callback_url(url: str) -> str:
    """Validate a callback URL at the time it is accepted. Returns the stripped URL."""
    url = url.strip()
    try:
        parts = urlsplit(url)
        port = parts.port  # raises on a malformed port
    except ValueError as exc:
        raise UnsafeUrl("callback_url is not a valid URL") from exc
    if parts.scheme not in ("http", "https"):
        raise UnsafeUrl("callback_url must be an http(s) URL")
    if get_settings().ENVIRONMENT == "production" and parts.scheme != "https":
        raise UnsafeUrl("callback_url must use https in production")
    if parts.username is not None or parts.password is not None:
        raise UnsafeUrl("callback_url must not contain credentials")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeUrl("callback_url must include a host")
    if port == 0:
        raise UnsafeUrl("callback_url has an invalid port")
    if _private_allowed():
        return url
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise UnsafeUrl("callback_url must not point to a local or internal host")
    try:
        ipaddress.ip_address(host)
        is_literal = True
    except ValueError:
        is_literal = False
    if is_literal and not is_public_ip(host):
        raise UnsafeUrl("callback_url must not point to a private, loopback or link-local address")
    if not is_literal and "." not in host:
        raise UnsafeUrl("callback_url must use a fully qualified host name")
    return url


def pin_public_address(url: str) -> PinnedUrl:
    """Resolve the URL's host and return a version that connects to one vetted public IP.

    Raises UnsafeUrl if the URL is invalid or the host resolves to any non-public address."""
    check_callback_url(url)
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    host_header = parts.netloc.rsplit("@", 1)[-1]
    if _private_allowed():
        return PinnedUrl(url=url, host=host, host_header=host_header)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeUrl(f"callback host '{host}' could not be resolved") from exc
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise UnsafeUrl(f"callback host '{host}' did not resolve")
    bad = [a for a in addresses if not is_public_ip(a)]
    if bad:
        raise UnsafeUrl(f"callback host '{host}' resolves to a non-public address ({bad[0]})")
    # Prefer IPv4: plenty of hosts publish AAAA records without a working IPv6 route.
    ip = sorted(addresses, key=lambda a: ":" in a)[0].split("%", 1)[0]
    ip_netloc = f"[{ip}]" if ":" in ip else ip
    if parts.port:
        ip_netloc += f":{parts.port}"
    pinned = urlunsplit((parts.scheme, ip_netloc, parts.path, parts.query, ""))
    return PinnedUrl(url=pinned, host=host, host_header=host_header)
