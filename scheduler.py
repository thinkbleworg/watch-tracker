from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from config import config
from tracker import Tracker, TrackerRunResult


logger = logging.getLogger(__name__)


class TrackerScheduler:
    """
    Runs the HMT tracker repeatedly at a fixed interval.

    The scheduler uses a background thread so it remains independent
    from FastAPI's event loop.

    Scheduled and manual tracker runs share one execution lock, so only
    one tracker run can execute at a time. A failure in one run is
    isolated to that run and does not terminate the scheduler worker.
    """

    def __init__(
        self,
        tracker: Tracker,
        *,
        interval_seconds: int | None = None,
        alert_callback: Callable[[Any], Any] | None = None,
    ) -> None:
        self.tracker = tracker

        self.interval_seconds = (
            interval_seconds
            if interval_seconds is not None
            else config.scrape_interval_seconds
        )

        self.alert_callback = alert_callback

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Protect scheduler lifecycle/state.
        self._lock = threading.Lock()

        # Prevent scheduled and manual tracker runs from overlapping.
        self._execution_lock = threading.Lock()

        self._running = False
        self._last_result: TrackerRunResult | None = None
        self._last_error: str | None = None
        self._last_run_at: float | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        """Return whether the scheduler worker is running."""
        with self._lock:
            return self._running

    @property
    def execution_running(self) -> bool:
        """Return whether a tracker execution is currently running."""
        return self._execution_lock.locked()

    @property
    def last_result(self) -> TrackerRunResult | None:
        with self._lock:
            return self._last_result

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    @property
    def last_run_at(self) -> float | None:
        with self._lock:
            return self._last_run_at

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        *,
        run_immediately: bool = False,
    ) -> None:
        """
        Start the background scheduler.

        Args:
            run_immediately:
                If True, perform one tracker run immediately before
                entering the normal interval loop.
        """
        with self._lock:
            if self._running:
                logger.warning(
                    "Tracker scheduler is already running"
                )
                return

            self._stop_event.clear()
            self._running = True

            self._thread = threading.Thread(
                target=self._worker,
                args=(run_immediately,),
                name="hmt-tracker-scheduler",
                daemon=True,
            )

            self._thread.start()

        logger.info(
            "Tracker scheduler started: interval=%s seconds",
            self.interval_seconds,
        )

    def stop(
        self,
        timeout: float = 10.0,
    ) -> None:
        """Stop the background scheduler."""
        with self._lock:
            if not self._running:
                return

            self._stop_event.set()
            thread = self._thread

        if thread and thread.is_alive():
            thread.join(timeout=timeout)

        with self._lock:
            self._running = False
            self._thread = None

        logger.info("Tracker scheduler stopped")

    # ------------------------------------------------------------------
    # Manual execution
    # ------------------------------------------------------------------

    def run_now(self) -> TrackerRunResult:
        """
        Run the tracker immediately.

        If another tracker execution is already active, fail with a
        clear RuntimeError. The background scheduler itself continues
        independently.
        """
        logger.info("Manual tracker run requested")
        return self._execute_run()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return scheduler status suitable for the dashboard/API."""
        result = self.last_result

        return {
            "running": self.running,
            "execution_running": self.execution_running,
            "interval_seconds": self.interval_seconds,
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "last_result": self._result_to_dict(result),
        }

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    def _worker(
        self,
        run_immediately: bool,
    ) -> None:
        """
        Run the scheduler loop.

        Each tracker execution is isolated from the loop. This is
        important in production: a transient scraper/network/Telegram
        exception must not kill the 60-second scheduler permanently.
        """
        try:
            if run_immediately:
                self._run_safely("startup")

            while not self._stop_event.wait(self.interval_seconds):
                self._run_safely("scheduled")

        except Exception:
            # This should only be reached for an unexpected scheduler
            # lifecycle/threading error, not an ordinary tracker failure.
            logger.exception(
                "Tracker scheduler worker crashed unexpectedly"
            )

        finally:
            with self._lock:
                self._running = False

            logger.info("Tracker scheduler worker stopped")

    def _run_safely(
        self,
        trigger: str,
    ) -> TrackerRunResult | None:
        """
        Execute one tracker run without allowing an execution exception
        to terminate the scheduler loop.
        """
        try:
            return self._execute_run()

        except RuntimeError as exc:
            # A concurrent manual/scheduled execution can legitimately
            # hit the execution lock. Keep the scheduler alive.
            logger.warning(
                "Tracker %s run skipped: %s",
                trigger,
                exc,
            )

        except Exception:
            logger.exception(
                "Tracker %s run failed; scheduler will continue",
                trigger,
            )

        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute_run(
        self,
    ) -> TrackerRunResult:
        """
        Execute exactly one tracker run and store its result.

        Only one execution may enter this method at a time.
        """
        acquired = self._execution_lock.acquire(
            blocking=False
        )

        if not acquired:
            raise RuntimeError(
                "A tracker run is already in progress."
            )

        started_at = time.time()

        try:
            result = self.tracker.run(
                alert_callback=self.alert_callback,
            )

            with self._lock:
                self._last_result = result
                self._last_error = None
                self._last_run_at = started_at

            logger.info(
                "Tracker run completed: success=%s sources=%s "
                "new_watches=%s alerts=%s",
                result.success,
                len(result.sources),
                result.new_products,
                result.alerts_created,
            )

            return result

        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._last_run_at = started_at

            logger.exception("Tracker run failed")
            raise

        finally:
            self._execution_lock.release()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _result_to_dict(
        result: TrackerRunResult | None,
    ) -> dict[str, Any] | None:
        if result is None:
            return None

        return {
            "run_id": result.run_id,
            "success": result.success,
            "sources": [
                {
                    "source": source.source,
                    "success": source.success,
                    "products_found": source.products_found,
                    "new_products": source.new_products,
                    "in_stock_products": source.in_stock_products,
                    "alerts_created": source.alerts_created,
                    "error": source.error,
                }
                for source in result.sources
            ],
            "total_products": result.total_products,
            "new_products": result.new_products,
            "in_stock_products": result.in_stock_products,
            "alerts_created": result.alerts_created,
            "first_run_seed": result.first_run_seed,
            "error": result.error,
        }