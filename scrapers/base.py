"""
Base Scraper

Shared functionality for all scrapers.
"""

import time
from abc import ABC, abstractmethod

import requests

from config import (
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    USER_AGENT,
)


class BaseScraper(ABC):
    """
    Base class for all scrapers.
    """

    def __init__(self):

        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
            }
        )

    # ------------------------------------------------------------------

    def get(
        self,
        url,
        headers=None,
        params=None,
    ):
        """
        HTTP GET with retry.
        """

        last_error = None

        for attempt in range(MAX_RETRIES):

            try:

                response = self.session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )

                print(response.status_code)
                print(response.text)
                response.raise_for_status()

                return response

            except Exception as ex:

                last_error = ex

                print(
                    f"[GET] Retry {attempt + 1}/{MAX_RETRIES}"
                )

                time.sleep(2)

        raise last_error

    # ------------------------------------------------------------------

    def post(
        self,
        url,
        headers=None,
        data=None,
        json=None,
    ):
        """
        HTTP POST with retry.
        """

        last_error = None

        for attempt in range(MAX_RETRIES):

            try:

                response = self.session.post(
                    url,
                    headers=headers,
                    data=data,
                    json=json,
                    timeout=REQUEST_TIMEOUT,
                )

                response.raise_for_status()

                return response

            except Exception as ex:

                last_error = ex

                print(
                    f"[POST] Retry {attempt + 1}/{MAX_RETRIES}"
                )

                time.sleep(2)

        raise last_error

    # ------------------------------------------------------------------

    @staticmethod
    def clean(text):
        """
        Clean whitespace.
        """

        if text is None:
            return ""

        return " ".join(str(text).split()).strip()

    # ------------------------------------------------------------------

    @staticmethod
    def build_price(price):
        """
        Convert numeric price to ₹ format.
        """

        if price is None:
            return ""

        price = str(price).replace("₹", "").strip()

        return f"₹{price}"

    # ------------------------------------------------------------------

    @staticmethod
    def available(flag):
        """
        Convert bool -> stock text.
        """

        return (
            "Available"
            if flag
            else "Out of Stock"
        )

    # ------------------------------------------------------------------

    @abstractmethod
    def scrape(self):
        """
        Must return

        {
            product_id: Watch
        }
        """

        raise NotImplementedError