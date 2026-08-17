import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .config import settings

PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::/128"),
]


class LinkError(Exception):
    def __init__(self, reason: str, permanent: bool = True):
        super().__init__(reason)
        self.reason = reason
        self.permanent = permanent


def _host_matches(host: str, pattern: str) -> bool:
    if pattern == host:
        return True
    if pattern.startswith("*."):
        return host.endswith(pattern[1:])
    return False


def is_allowed_domain(host: str) -> bool:
    host = host.lower()
    return any(_host_matches(host, p) for p in settings.domain_allowlist)


def resolve_private_ip(host: str) -> str | None:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return "khong phan giai duoc hostname"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return str(ip)
    return None


def normalize_url(raw: str) -> str:
    raw = raw.strip()
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raise LinkError("Link phai bat dau bang http(s)://")
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise LinkError("Chi ho tro link https", permanent=True)
    try:
        port = parsed.port
    except ValueError:
        raise LinkError("Link co cong khong hop le")
    if port is not None and port != 443:
        raise LinkError("Chi ho tro cong 443 (https chuan)")
    if parsed.username or parsed.password:
        raise LinkError("Link khong duoc chua ten dang nhap/mat khau")
    return raw


def validate_link(raw: str) -> str:
    url = normalize_url(raw)
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not is_allowed_domain(host):
        allowed = ", ".join(settings.domain_allowlist)
        raise LinkError(f"Domain '{host}' khong nam trong danh sach cho phep: {allowed}")
    blocked = resolve_private_ip(host)
    if blocked:
        raise LinkError(f"Host '{host}' giai ve IP noi bo ({blocked}) - bi chan")
    return url


@dataclass
class ValidationResult:
    url: str
    adapter: str = ""
    warnings: list[str] = field(default_factory=list)
