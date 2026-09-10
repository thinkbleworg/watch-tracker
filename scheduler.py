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

    The scheduler is intentionally implemented with a background thread
    rather than asyncio. This keeps it independent from FastAPI's event
    loop and makes manual "Run Now" calls safe because Tracker itself
    prevents concurrent runs.
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
            else config.scheduler_interval_seconds
        )
        self.alert_callback = alert_callback

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        self._running = False
        self._last_result: TrackerRunResult | None = None
        self._last_error: str | None = None
        self._last_run_at: float | None = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def last_result(self) -> TrackerRunResult | None:
        return self._last_result

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_run_at(self) -> float | None:
        return self._last_run_at

    def start(self, *, run_immediately: bool = False) -> None:
        """
        Start the background scheduler.

        Args:
            run_immediately:
                If True, perform one tracker run immediately before
                entering the normal interval loop.
        """
        with self._lock:
            if self._running:
                logger.warning("Tracker scheduler is already running")
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

    def stop(self, timeout: float = 10.0) -> None:
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

    def run_now(self) -> TrackerRunResult:
        """
        Run the tracker immediately.

        This is used by the dashboard's "Run Now" button.
        """
        logger.info("Manual tracker run requested")

        return self._execute_run()

    def status(self) -> dict[str, Any]:
        """Return scheduler status suitable for the dashboard/API."""
        result = self._last_result

        return {
            "running": self.running,
            "interval_seconds": self.interval_seconds,
            "last_run_at": self._last_run_at,
            "last_error": self._last_error,
            "last_result": self._result_to_dict(result),
        }

    def _worker(self, run_immediately: bool) -> None:
        try:
            if run_immediately:
                self._execute_run()

            while not self._stop_event.wait(self.interval_seconds):
                self._execute_run()

        except Exception:
            logger.exception("Tracker scheduler worker crashed")

        finally:
            with self._lock:
                self._running = False

    def _execute_run(self) -> TrackerRunResult:
        """
        Execute exactly one tracker run and store its result.
        """
        try:
            result = self.tracker.run(
                alert_callback=self.alert_callback,
            )

            with self._lock:
                self._last_result = result
                self._last_error = None
                self._last_run_at = time.time()

            logger.info(
                "Tracker run completed: success=%s sources=%s "
                "new_watches=%s alerts=%s",
                result.success,
                result.sources_succeeded,
                result.new_watches,
                result.alerts_created,
            )

            return result

        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._last_run_at = time.time()

            logger.exception("Tracker run failed")

            raise

    @staticmethod
    def _result_to_dict(
        result: TrackerRunResult | None,
    ) -> dict[str, Any] | None:
        if result is None:
            return None

        return {
            "success": result.success,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "sources_succeeded": result.sources_succeeded,
            "sources_failed": result.sources_failed,
            "new_watches": result.new_watches,
            "alerts_created": result.alerts_created,
            "errors": result.errors,
        }