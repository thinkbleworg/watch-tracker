from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable

from config import TrackerConfig, config, enabled_sources, get_source
from database import Database
from scrapers.hmt_official import OfficialHMTScraper
from scrapers.hmt_store import HMTStoreScraper
from models import AlertState, TrackingRule, Watch

logger = logging.getLogger(__name__)


@dataclass
class AlertCandidate:
    """
    A watch that qualifies for a Telegram alert.

    The Telegram notifier will consume this object later.
    """

    watch: Watch
    alert_type: str
    rule_ids: list[str] = field(default_factory=list)


@dataclass
class SourceRunResult:
    """Result of processing one source."""

    source: str

    success: bool = False
    products_found: int = 0
    new_products: int = 0
    in_stock_products: int = 0

    alerts_created: int = 0

    error: str | None = None


@dataclass
class TrackerRunResult:
    """Summary of a complete tracker execution."""

    run_id: int

    success: bool

    sources: list[SourceRunResult] = field(
        default_factory=list
    )

    total_products: int = 0
    new_products: int = 0
    in_stock_products: int = 0
    alerts_created: int = 0

    first_run_seed: bool = False

    error: str | None = None

    @property
    def failed_sources(self) -> list[SourceRunResult]:
        """Return source runs that failed."""

        return [
            result
            for result in self.sources
            if not result.success
        ]


class Tracker:
    """
    Main HMT tracking engine.

    This class deliberately does not send Telegram messages itself.

    Its responsibility ends at:
        scrape -> compare -> persist -> create alert records

    The Telegram notifier can then send those pending records.

    This separation is important because a Telegram failure should not
    cause the scraper to repeat or recreate catalogue events.
    """

    def __init__(
        self,
        database: Database,
        *,
        tracker_config: TrackerConfig = config,
    ) -> None:
        self.db = database
        self.config = tracker_config

        self._run_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        alert_callback: Callable[
            [AlertCandidate],
            None,
        ]
        | None = None,
    ) -> TrackerRunResult:
        """
        Execute one complete tracker run.

        Args:
            alert_callback:
                Optional callback invoked after an alert has been
                persisted. The callback is intended for the Telegram
                notifier.

        Returns:
            TrackerRunResult containing source/run statistics.
        """

        # Prevent two scheduler/manual runs from scraping simultaneously.
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError(
                "A tracker run is already in progress."
            )

        run_id = self.db.start_scrape_run()

        result = TrackerRunResult(
            run_id=run_id,
            success=True,
        )

        try:
            logger.info(
                "Starting tracker run %s.",
                run_id,
            )

            rules = self.db.get_tracking_rules(
                enabled_only=True
            )

            first_run = self._is_first_run()

            result.first_run_seed = first_run

            for source_config in enabled_sources():
                source_result = self._run_source(
                    source_config.name,
                    rules=rules,
                    seed_only=first_run,
                    alert_callback=alert_callback,
                )

                result.sources.append(
                    source_result
                )

                result.total_products += (
                    source_result.products_found
                )

                result.new_products += (
                    source_result.new_products
                )

                result.in_stock_products += (
                    source_result.in_stock_products
                )

                result.alerts_created += (
                    source_result.alerts_created
                )

            # A run is considered successful if at least one enabled
            # source succeeded. Individual source failures are preserved
            # in the result and source_status table.
            successful_sources = [
                source
                for source in result.sources
                if source.success
            ]

            result.success = bool(
                successful_sources
            )

            if not result.success:
                result.error = (
                    "All enabled sources failed."
                )

            self.db.finish_scrape_run(
                run_id,
                status=(
                    "success"
                    if result.success
                    else "failed"
                ),
                total_found=result.total_products,
                new_products=result.new_products,
                in_stock=result.in_stock_products,
                alerts_created=result.alerts_created,
                error=result.error,
            )

            logger.info(
                "Tracker run %s finished: "
                "success=%s products=%s new=%s alerts=%s",
                run_id,
                result.success,
                result.total_products,
                result.new_products,
                result.alerts_created,
            )

            return result

        except Exception as exc:
            logger.exception(
                "Tracker run %s failed.",
                run_id,
            )

            result.success = False
            result.error = str(exc)

            self.db.finish_scrape_run(
                run_id,
                status="failed",
                error=str(exc),
            )

            return result

        finally:
            self._run_lock.release()

    # ------------------------------------------------------------------
    # Source processing
    # ------------------------------------------------------------------

    def _run_source(
        self,
        source: str,
        *,
        rules: list[TrackingRule],
        seed_only: bool,
        alert_callback: Callable[
            [AlertCandidate],
            None,
        ]
        | None,
    ) -> SourceRunResult:
        """Scrape, compare and persist one source."""

        result = SourceRunResult(
            source=source
        )

        if not self.db.is_source_enabled(source):
            logger.info(
                "Source %s is disabled.",
                source,
            )

            result.success = True

            return result

        try:
            watches = self._scrape_source(
                source
            )

            if not watches:
                raise RuntimeError(
                    f"Source {source} returned no watches."
                )

            result.success = True
            result.products_found = len(
                watches
            )

            result.in_stock_products = sum(
                1
                for watch in watches
                if watch.in_stock
            )

            self.db.set_source_success(
                source,
                products_found=len(watches),
            )

            logger.info(
                "Source %s returned %s products.",
                source,
                len(watches),
            )

            for watch in watches:
                is_new = not self.db.watch_exists(
                    watch.id
                )

                if is_new:
                    result.new_products += 1

                self._process_watch(
                    watch,
                    is_new=is_new,
                    rules=rules,
                    seed_only=seed_only,
                    result=result,
                    alert_callback=alert_callback,
                )

            return result

        except Exception as exc:
            result.success = False
            result.error = str(exc)

            self.db.set_source_failure(
                source,
                error=str(exc),
            )

            logger.exception(
                "Source %s failed. Existing catalogue state "
                "will not be treated as out of stock.",
                source,
            )

            return result

    def _scrape_source(
        self,
        source: str,
    ) -> list[Watch]:
        """Construct the appropriate scraper and execute it."""

        source_config = get_source(
            source
        )

        if source == "hmt.in":
            scraper = OfficialHMTScraper(
                source_config,
                timeout_seconds=(
                    self.config.request_timeout_seconds
                ),
                retries=self.config.request_retries,
            )

        elif source == "hmt.store":
            scraper = HMTStoreScraper(
                source_config,
                shop_id=self.config.store_shop_id,
                page_size=self.config.store_page_size,
                timeout_seconds=(
                    self.config.request_timeout_seconds
                ),
                retries=self.config.request_retries,
            )

        else:
            raise ValueError(
                f"No scraper registered for source: {source}"
            )

        return scraper.scrape()

    # ------------------------------------------------------------------
    # Watch processing
    # ------------------------------------------------------------------

    def _process_watch(
        self,
        watch: Watch,
        *,
        is_new: bool,
        rules: list[TrackingRule],
        seed_only: bool,
        result: SourceRunResult,
        alert_callback: Callable[
            [AlertCandidate],
            None,
        ]
        | None,
    ) -> None:
        """
        Process one discovered watch.

        The catalogue is always updated.

        Alert creation is deliberately separate from catalogue updates.
        """

        if is_new:
            self.db.save_watch(
                watch
            )

            # First run is catalogue seeding only.
            if seed_only and self.config.seed_catalogue_silently:
                logger.debug(
                    "Seeded %s silently.",
                    watch.id,
                )

                return

            should_alert = (
                self.config.alert_new_products_only
                and self.config.alert_only_when_in_stock
                and watch.in_stock
            )

        else:
            existing = self.db.get_watch(
                watch.id
            )

            if existing is None:
                # Extremely unlikely because we checked existence above,
                # but treating it as a new item is safer than losing it.
                self.db.save_watch(
                    watch
                )

                should_alert = (
                    self.config.alert_new_products_only
                    and self.config.alert_only_when_in_stock
                    and watch.in_stock
                    and not seed_only
                )

            else:
                # Preserve the catalogue's permanent identity and update
                # the latest observation.
                existing.update_from(
                    watch
                )

                self.db.save_watch(
                    existing
                )

                # Default behavior: existing watches never alert.
                should_alert = False

        if not should_alert:
            return

        matching_rules = [
            rule
            for rule in rules
            if rule.matches(watch)
        ]

        if not matching_rules:
            logger.debug(
                "New in-stock watch %s does not match "
                "any tracking rule.",
                watch.id,
            )

            return

        # One watch should produce one Telegram alert even if multiple
        # rules match it.
        alert_id = self.db.create_alert(
            watch=watch,
            alert_type="new",
            status="pending",
            telegram_chat_id=(
                self.config.telegram.chat_id
                or None
            ),
        )

        result.alerts_created += 1

        candidate = AlertCandidate(
            watch=watch,
            alert_type="new",
            rule_ids=[
                rule.id
                for rule in matching_rules
            ],
        )

        logger.info(
            "Created alert %s for new watch %s.",
            alert_id,
            watch.name,
        )

        if alert_callback is not None:
            try:
                alert_callback(
                    candidate
                )

            except Exception as exc:
                # The alert record remains pending/failed and can be
                # retried by the notification layer.
                self.db.mark_alert_failed(
                    alert_id,
                    str(exc),
                )

                logger.exception(
                    "Alert callback failed for %s.",
                    watch.id,
                )

    # ------------------------------------------------------------------
    # First-run detection
    # ------------------------------------------------------------------

    def _is_first_run(self) -> bool:
        """
        Determine whether the catalogue has ever been seeded.

        We check the catalogue itself rather than scrape history because
        a failed run should never permanently disable initial seeding.
        """

        return (
            self.db.count_watches() == 0
        )

    # ------------------------------------------------------------------
    # Utility operations for the UI
    # ------------------------------------------------------------------

    def preview_matches(
        self,
        watch: Watch,
    ) -> list[TrackingRule]:
        """
        Return enabled tracking rules matching a watch.

        Useful for the catalogue/configuration UI.
        """

        rules = self.db.get_tracking_rules(
            enabled_only=True
        )

        return [
            rule
            for rule in rules
            if rule.matches(watch)
        ]

    def is_tracked(
        self,
        watch: Watch,
    ) -> bool:
        """Return whether at least one enabled rule tracks a watch."""

        return bool(
            self.preview_matches(
                watch
            )
        )

    def get_pending_alert_count(self) -> int:
        """Return alerts waiting to be delivered."""

        return len(
            self.db.get_alerts(
                status="pending",
                limit=100000,
            )
        )