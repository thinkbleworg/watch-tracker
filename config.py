from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable safely."""

    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable safely."""

    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name!r} must be an integer."
        ) from exc


@dataclass(frozen=True)
class SourceConfig:
    """Configuration for one HMT product source."""

    name: str
    enabled: bool
    base_url: str
    timeout_seconds: int = 30


@dataclass(frozen=True)
class TelegramConfig:
    """Telegram bot configuration."""

    bot_token: str = ""
    chat_id: str = ""

    @property
    def enabled(self) -> bool:
        """Telegram is enabled only when both values are configured."""

        return bool(self.bot_token and self.chat_id)


@dataclass(frozen=True)
class TrackerConfig:
    """Application-wide configuration."""

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    database_path: str = "data/hmt_tracker.db"

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------

    scrape_interval_seconds: int = 60
    run_on_startup: bool = True

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    request_timeout_seconds: int = 30
    request_retries: int = 3

    # ------------------------------------------------------------------
    # HMT sources
    # ------------------------------------------------------------------

    sources: tuple[SourceConfig, ...] = field(
        default_factory=lambda: (
            SourceConfig(
                name="hmt.in",
                enabled=True,
                base_url="https://hmtwatches.in",
            ),
            SourceConfig(
                name="hmt.store",
                enabled=True,
                base_url="https://hmtwatches.store",
            ),
        )
    )

    # ------------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------------

    telegram: TelegramConfig = field(
        default_factory=TelegramConfig
    )

    # ------------------------------------------------------------------
    # Alert behaviour
    # ------------------------------------------------------------------

    # The first successful scrape seeds the catalogue silently.
    seed_catalogue_silently: bool = True

    # Only newly discovered products should generate alerts.
    alert_new_products_only: bool = True

    # New products must currently be in stock.
    alert_only_when_in_stock: bool = True

    # Do not notify on ordinary stock transitions by default.
    alert_back_in_stock: bool = False
    alert_out_of_stock: bool = False

    # Price changes are catalogue changes, not Telegram alerts.
    alert_price_changes: bool = False

    # Repeat alerts while a tracked watch remains in stock.
    alert_repeat_enabled: bool = False
    alert_repeat_interval_minutes: int = 10

    # ------------------------------------------------------------------
    # Store API
    # ------------------------------------------------------------------

    store_shop_id: int = 48236
    store_page_size: int = 100

    # ------------------------------------------------------------------
    # Official HMT website
    # ------------------------------------------------------------------

    official_filter_path: str = "/filter_products"
    official_all_products_path: str = "/all_product"
    official_product_view_path: str = "/product_view"

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False


def load_config() -> TrackerConfig:
    """
    Build application configuration from environment variables.

    Environment variables are optional for local development.
    Production secrets, especially Telegram credentials, should be
    supplied through the deployment environment rather than committed
    to source control.
    """

    telegram = TelegramConfig(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )

    sources = (
        SourceConfig(
            name="hmt.in",
            enabled=_env_bool("HMT_IN_ENABLED", True),
            base_url=os.getenv(
                "HMT_IN_BASE_URL",
                "https://hmtwatches.in",
            ).rstrip("/"),
            timeout_seconds=_env_int(
                "HMT_IN_TIMEOUT_SECONDS",
                30,
            ),
        ),
        SourceConfig(
            name="hmt.store",
            enabled=_env_bool("HMT_STORE_ENABLED", True),
            base_url=os.getenv(
                "HMT_STORE_BASE_URL",
                "https://hmtwatches.store",
            ).rstrip("/"),
            timeout_seconds=_env_int(
                "HMT_STORE_TIMEOUT_SECONDS",
                30,
            ),
        ),
    )

    return TrackerConfig(
        database_path=os.getenv(
            "DATABASE_PATH",
            "data/hmt_tracker.db",
        ),

        scrape_interval_seconds=_env_int(
            "SCRAPE_INTERVAL_SECONDS",
            300,
        ),

        run_on_startup=_env_bool(
            "RUN_ON_STARTUP",
            True,
        ),

        request_timeout_seconds=_env_int(
            "REQUEST_TIMEOUT_SECONDS",
            30,
        ),

        request_retries=_env_int(
            "REQUEST_RETRIES",
            3,
        ),

        sources=sources,

        telegram=telegram,

        seed_catalogue_silently=_env_bool(
            "SEED_CATALOGUE_SILENTLY",
            True,
        ),

        alert_new_products_only=_env_bool(
            "ALERT_NEW_PRODUCTS_ONLY",
            True,
        ),

        alert_only_when_in_stock=_env_bool(
            "ALERT_ONLY_WHEN_IN_STOCK",
            True,
        ),

        alert_back_in_stock=_env_bool(
            "ALERT_BACK_IN_STOCK",
            False,
        ),

        alert_out_of_stock=_env_bool(
            "ALERT_OUT_OF_STOCK",
            False,
        ),

        alert_price_changes=_env_bool(
            "ALERT_PRICE_CHANGES",
            False,
        ),

        alert_repeat_enabled=_env_bool(
            "ALERT_REPEAT_ENABLED",
            False,
        ),

        alert_repeat_interval_minutes=_env_int(
            "ALERT_REPEAT_INTERVAL_MINUTES",
            10,
        ),

        store_shop_id=_env_int(
            "STORE_SHOP_ID",
            48236,
        ),

        store_page_size=_env_int(
            "STORE_PAGE_SIZE",
            100,
        ),

        official_filter_path=os.getenv(
            "HMT_IN_FILTER_PATH",
            "/filter_products",
        ),

        official_all_products_path=os.getenv(
            "HMT_IN_ALL_PRODUCTS_PATH",
            "/all_product",
        ),

        official_product_view_path=os.getenv(
            "HMT_IN_PRODUCT_VIEW_PATH",
            "/product_view",
        ),

        host=os.getenv(
            "HOST",
            "0.0.0.0",
        ),

        port=_env_int(
            "PORT",
            8000,
        ),

        debug=_env_bool(
            "DEBUG",
            False,
        ),
    )


# One application-wide configuration object.
config = load_config()


def get_source(name: str) -> SourceConfig:
    """Return a configured source by name."""

    for source in config.sources:
        if source.name == name:
            return source

    raise KeyError(f"Unknown source: {name}")


def enabled_sources() -> tuple[SourceConfig, ...]:
    """Return only currently enabled sources."""

    return tuple(
        source
        for source in config.sources
        if source.enabled
    )


def database_path() -> Path:
    """Return the configured database path as a Path object."""

    return Path(config.database_path)