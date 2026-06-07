"""HTTP-слой: сессия с ретраями, вежливый rate limit и проверка robots.txt.

Один экземпляр Fetcher потокобезопасен и используется всеми воркерами:
- ретраи 5xx/сетевых ошибок через urllib3.Retry (без внешних зависимостей);
- per-host пауза не меньше min_delay (или Crawl-delay из robots.txt);
- уважение Disallow из robots.txt (RESPECT_ROBOTS).
"""
from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from freedom_parser.common.robots import RobotsRules

log = logging.getLogger("freedom_parser.http")


class Fetcher:
    def __init__(
        self,
        user_agent: str = config.USER_AGENT,
        min_delay: float = config.DEFAULT_MIN_DELAY,
        timeout: int = config.REQUEST_TIMEOUT,
        max_retries: int = config.MAX_RETRIES,
        respect_robots: bool = config.RESPECT_ROBOTS,
    ) -> None:
        self.user_agent = user_agent
        self.min_delay = min_delay
        self.timeout = timeout
        self.respect_robots = respect_robots

        self.session = requests.Session()
        retry = Retry(
            total=max_retries,
            backoff_factor=0.8,                 # 0.8, 1.6, 3.2, ... сек
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "ru,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        self._lock = threading.Lock()
        self._last_request: dict[str, float] = {}   # host -> ts последнего запроса
        self._robots: dict[str, RobotsRules] = {}    # host -> правила

    # --- robots.txt (longest-match, Google-семантика) ---
    def _robots_for(self, url: str) -> RobotsRules:
        host = urlsplit(url).netloc
        with self._lock:
            rules = self._robots.get(host)
            if rules is not None:
                return rules
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{host}/robots.txt"
        try:
            resp = self.session.get(robots_url, timeout=self.timeout)
            text = resp.text if resp.status_code == 200 else ""
        except requests.RequestException:
            text = ""
        rules = RobotsRules.parse(text, self.user_agent)
        with self._lock:
            self._robots[host] = rules
        return rules

    def can_fetch(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        return self._robots_for(url).allowed(url)

    def _effective_delay(self, url: str) -> float:
        """Берём максимум из min_delay и Crawl-delay из robots.txt."""
        delay = self.min_delay
        if self.respect_robots:
            crawl = self._robots_for(url).crawl_delay
            if crawl:
                delay = max(delay, float(crawl))
        return delay

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        delay = self._effective_delay(url)
        with self._lock:
            last = self._last_request.get(host, 0.0)
            wait = delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            self._last_request[host] = time.monotonic()

    # --- основной метод ---
    def get(self, url: str) -> requests.Response | None:
        """GET с уважением robots/rate limit. None — если запрещено robots."""
        if not self.can_fetch(url):
            log.warning("robots.txt запрещает: %s", url)
            return None
        self._throttle(url)
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp
