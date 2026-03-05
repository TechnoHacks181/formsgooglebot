import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Optional

from data import USER_AGENTS

log = logging.getLogger(__name__)

# ── Constantes ──────────────────────────────────────────────────
FORM_URL_RE   = re.compile(r"^https://docs\.google\.com/forms/d/e/[\w-]+/viewform(\?.*)?$")
PROXY_RE      = re.compile(r"^(https?|socks[45])://")
MAX_RESPONSES = 500
MIN_DELAY     = 1.0
MAX_TIMEOUT   = 120


# ── Config ───────────────────────────────────────────────────────
@dataclass
class BotConfig:
    url: str
    count:        int   = 1
    delay_min:    float = 2.0
    delay_max:    float = 5.0
    headless:     bool  = True
    timeout:      int   = 15
    threads:      int   = 1
    proxy:        Optional[str] = None
    proxy_file:   Optional[str] = None
    max_responses: int  = MAX_RESPONSES
    user_agents:  list  = field(default_factory=lambda: USER_AGENTS.copy())

    def __post_init__(self):
        self.url          = _validate_url(self.url)
        self.count        = max(1,   min(self.count,        MAX_RESPONSES))
        self.max_responses= max(1,   min(self.max_responses, MAX_RESPONSES))
        self.delay_min    = max(MIN_DELAY, self.delay_min)
        self.delay_max    = max(self.delay_min + 0.5, self.delay_max)
        self.timeout      = max(5, min(self.timeout, MAX_TIMEOUT))
        self.threads      = max(1, min(int(self.threads), 50))
        self.user_agents  = self.user_agents or USER_AGENTS.copy()

        if self.proxy:
            self.proxy = self.proxy.strip()
            if not PROXY_RE.match(self.proxy) or " " in self.proxy:
                raise ValueError(f"Proxy inválido: {self.proxy!r}")

    @classmethod
    def from_file(cls, path: str) -> "BotConfig":
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Config no encontrada: {path}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _drop_unknown_keys(data)
        return cls(**data)

    @classmethod
    def from_args(cls, args) -> "BotConfig":
        return cls(
            url=args.url,
            count=args.count,
            delay_min=max(MIN_DELAY, args.delay - 1),
            delay_max=args.delay + 2,
            headless=not args.no_headless,
            proxy=args.proxy,
            proxy_file=args.proxy_file,
            max_responses=args.max_responses,
            threads=args.threads,
        )


# ── Proxy Rotator ────────────────────────────────────────────────
class ProxyRotator:
    def __init__(self, filepath: str):
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"Archivo de proxies no encontrado: {filepath}")
        self._lock = threading.Lock()
        self._idx  = 0
        with open(filepath, encoding="utf-8") as f:
            self.proxies = [
                line.strip() for line in f
                if line.strip() and not line.startswith("#") and PROXY_RE.match(line.strip())
            ]
        log.info(f"Cargados {len(self.proxies)} proxies desde {filepath}")

    def next(self) -> Optional[str]:
        if not self.proxies:
            return None
        with self._lock:
            proxy = self.proxies[self._idx]
            self._idx = (self._idx + 1) % len(self.proxies)
            return proxy


# ── Helpers privados ─────────────────────────────────────────────
_ALLOWED_KEYS = {
    "url", "count", "delay_min", "delay_max", "headless", "timeout",
    "proxy", "proxy_file", "max_responses", "user_agents", "threads",
}

def _validate_url(url: str) -> str:
    url = (url or "").strip()
    if not FORM_URL_RE.match(url):
        raise ValueError(
            "URL inválida. Formato esperado:\n"
            "https://docs.google.com/forms/d/e/FORM_ID/viewform"
        )
    return url

def _drop_unknown_keys(data: dict) -> None:
    unknown = set(data.keys()) - _ALLOWED_KEYS
    if unknown:
        log.warning(f"Claves desconocidas en config ignoradas: {unknown}")
        for k in list(unknown):   # itera sobre copia, modifica el original
            data.pop(k, None)
