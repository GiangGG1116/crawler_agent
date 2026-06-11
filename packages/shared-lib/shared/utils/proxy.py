"""Proxy rotation — manages a pool of proxy servers.

Supports round-robin, random, and least-used rotation strategies.
"""

import random
from collections import Counter
from pathlib import Path

from shared.utils.logger import get_logger

logger = get_logger(__name__)


class ProxyRotator:
    """
    Manages proxy rotation with multiple strategies.

    Loads proxies from a text file (one proxy per line) in format:
        http://user:pass@host:port
        socks5://host:port
    """

    def __init__(
        self,
        proxy_list_path: str | Path | None = None,
        strategy: str = "round_robin",
        proxies: list[str] | None = None,
    ):
        self._proxies: list[str] = []
        self._index = 0
        self._usage_counter: Counter[str] = Counter()
        self._strategy = strategy

        if proxies:
            self._proxies = proxies
        elif proxy_list_path:
            self._load_from_file(Path(proxy_list_path))
        else:
            from shared.utils.config import get_settings

            settings = get_settings()
            proxy_path = Path(settings.proxy_list_path)
            if proxy_path.exists():
                self._load_from_file(proxy_path)
            else:
                logger.warning(f"Proxy list file not found: {proxy_path}")

        if self._proxies:
            logger.info(f"Loaded {len(self._proxies)} proxies with strategy={strategy}")

    def _load_from_file(self, path: Path) -> None:
        try:
            with open(path) as f:
                self._proxies = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.startswith("#")
                ]
        except FileNotFoundError:
            logger.warning(f"Proxy file not found: {path}")

    @property
    def available(self) -> bool:
        return len(self._proxies) > 0

    @property
    def count(self) -> int:
        return len(self._proxies)

    def get_next(self) -> str | None:
        if not self._proxies:
            return None

        if self._strategy == "random":
            proxy = random.choice(self._proxies)
        elif self._strategy == "least_used":
            proxy = min(self._proxies, key=lambda p: self._usage_counter[p])
        else:
            proxy = self._proxies[self._index % len(self._proxies)]
            self._index += 1

        self._usage_counter[proxy] += 1
        return proxy

    def remove_proxy(self, proxy: str) -> None:
        if proxy in self._proxies:
            self._proxies.remove(proxy)
            logger.warning(
                f"Removed failed proxy: {proxy[:20]}... ({len(self._proxies)} remaining)"
            )

    def add_proxy(self, proxy: str) -> None:
        if proxy not in self._proxies:
            self._proxies.append(proxy)
