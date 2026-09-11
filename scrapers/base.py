from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


class BaseScraper(ABC):
    """
    Common base class for HMT source scrapers.

    Each source-specific scraper is responsible for:
      - discovering watches
      - determining stock
      - converting source data into Watch objects

    This class provides shared HTTP, HTML, identity, and parsing helpers.
    """

    SOURCE: str = ""
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        *,
        base_url: str,
        timeout: int = 30,
        retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = max(1, retries)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.USER_AGENT,
                "Accept": "*/*",
            }
        )

    @abstractmethod
    def scrape(self):
        """
        Scrape and return a list of normalized Watch objects.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def get(
        self,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        """GET a URL with simple retry handling."""
        url = self.absolute_url(path_or_url)
        return self._request(
            "GET",
            url,
            params=params,
            headers=headers,
        )

    def post(
        self,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        """POST a URL with simple retry handling."""
        url = self.absolute_url(path_or_url)
        return self._request(
            "POST",
            url,
            params=params,
            data=data,
            json=json,
            headers=headers,
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    json=json,
                    headers=headers,
                    timeout=self.timeout,
                )

                response.raise_for_status()
                return response

            except requests.RequestException as exc:
                last_error = exc

                if attempt == self.retries:
                    raise

        # Defensive fallback. The loop either returns or raises.
        raise RuntimeError(
            f"HTTP request failed: {method} {url}"
        ) from last_error

    def absolute_url(self, path_or_url: str) -> str:
        """
        Convert a relative source URL into an absolute URL.

        Existing absolute URLs are returned unchanged.
        """
        if not path_or_url:
            return self.base_url

        if path_or_url.startswith(("http://", "https://")):
            return path_or_url

        return urljoin(f"{self.base_url}/", path_or_url.lstrip("/"))

    # ------------------------------------------------------------------
    # HTML helpers
    # ------------------------------------------------------------------

    @staticmethod
    def soup(html: str) -> BeautifulSoup:
        """Parse HTML using lxml when available."""
        return BeautifulSoup(html, "lxml")

    @staticmethod
    def clean_text(value: Any) -> str:
        """Normalize whitespace in arbitrary text."""
        if value is None:
            return ""

        text = str(value)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def text_from(
        cls,
        element: Any,
        selector: str,
        default: str = "",
    ) -> str:
        """Extract cleaned text from a descendant selector."""
        if element is None:
            return default

        found = element.select_one(selector)
        if found is None:
            return default

        text = cls.clean_text(found.get_text(" ", strip=True))
        return text or default

    @staticmethod
    def attr(
        element: Any,
        name: str,
        default: str | None = None,
    ) -> str | None:
        """Read and clean an HTML attribute."""
        if element is None:
            return default

        value = element.get(name)

        if value is None:
            return default

        value = str(value).strip()
        return value or default

    # ------------------------------------------------------------------
    # Numeric / stock helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_int(value: Any) -> int | None:
        """
        Parse an integer from values such as:
          10
          "10"
          "10 available"
          "Stock: 10"
        """
        if value is None:
            return None

        if isinstance(value, bool):
            return int(value)

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(value)

        match = re.search(r"-?\d+", str(value))

        if not match:
            return None

        try:
            return int(match.group(0))
        except ValueError:
            return None

    @staticmethod
    def parse_price(value: Any) -> float | None:
        """
        Parse a price from values such as:
          1299
          "₹1,299"
          "Rs. 1299"
          "1,299.00"
        """
        if value is None:
            return None

        if isinstance(value, bool):
            return None

        if isinstance(value, (int, float)):
            return float(value)

        cleaned = re.sub(r"[^\d.,-]", "", str(value))
        cleaned = cleaned.replace(",", "")

        if not cleaned:
            return None

        try:
            return float(cleaned)
        except ValueError:
            return None

    @classmethod
    def stock_from_quantity(
        cls,
        quantity: Any,
    ) -> tuple[bool, int | None]:
        """
        Convert a quantity into the normalized stock representation.

        A quantity of zero or less means out of stock.
        Unknown quantity remains unknown rather than being invented.
        """
        count = cls.parse_int(quantity)

        if count is None:
            return False, None

        if count <= 0:
            return False, 0

        return True, count

    # ------------------------------------------------------------------
    # Identity helpers
    # ------------------------------------------------------------------

    @staticmethod
    def stable_id(
        *,
        source: str,
        value: str,
    ) -> str:
        """
        Generate a deterministic ID when the source does not expose
        a reliable product ID.
        """
        raw = f"{source}:{value}".strip().lower()

        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()[:24]

    @classmethod
    def id_from_url(
        cls,
        *,
        source: str,
        url: str,
    ) -> str:
        """Generate a stable ID based on a product URL."""
        return cls.stable_id(
            source=source,
            value=url,
        )

    # ------------------------------------------------------------------
    # Product metadata helpers
    # ------------------------------------------------------------------

    @classmethod
    def extract_labeled_value(
        cls,
        html_or_element: Any,
        label: str,
    ) -> str | None:
        """
        Extract a value following a label.

        Handles common product-description forms such as:

            Model No.: VG1L12
            Collection: Galaxy
            Gender: Women

        This intentionally remains conservative because product HTML
        differs between HMT pages.
        """
        if html_or_element is None:
            return None

        if hasattr(html_or_element, "get_text"):
            text = html_or_element.get_text(
                " ",
                strip=True,
            )
        else:
            text = str(html_or_element)

        pattern = re.compile(
            rf"{re.escape(label)}\s*[:\-]\s*([^|;,]+)",
            re.IGNORECASE,
        )

        match = pattern.search(text)

        if not match:
            return None

        value = cls.clean_text(match.group(1))

        return value or None

    @classmethod
    def extract_model_number(
        cls,
        text: str | None,
    ) -> str | None:
        """
        Conservative model-number extraction.

        Prefer explicit 'Model No.' labels when available.
        """
        if not text:
            return None

        match = re.search(
            r"Model\s*(?:No\.?|Number)?\s*[:\-]\s*"
            r"([A-Za-z0-9][A-Za-z0-9 ./_-]{1,50})",
            text,
            re.IGNORECASE,
        )

        if not match:
            return None

        value = cls.clean_text(match.group(1))

        return value or None

    # ------------------------------------------------------------------
    # Generic source utilities
    # ------------------------------------------------------------------

    @staticmethod
    def first_non_empty(*values: Any) -> Any:
        """Return the first non-empty value."""
        for value in values:
            if value is None:
                continue

            if isinstance(value, str):
                if value.strip():
                    return value.strip()
                continue

            return value

        return None

    @staticmethod
    def as_bool(value: Any) -> bool | None:
        """
        Convert common representations to bool.

        Returns None when the value cannot safely be interpreted.
        """
        if value is None:
            return None

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return bool(value)

        text = str(value).strip().lower()

        if text in {"true", "1", "yes", "y", "on"}:
            return True

        if text in {"false", "0", "no", "n", "off"}:
            return False

        return None

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def __enter__(self) -> "BaseScraper":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()