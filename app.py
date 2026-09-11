from __future__ import annotations

import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import config
from database import Database
from scheduler import TrackerScheduler
from notifier import TelegramNotifier
from tracker import Tracker


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("hmt-tracker")


# ---------------------------------------------------------------------------
# Application services
# ---------------------------------------------------------------------------

db = Database(config.database_path)

tracker = Tracker(db)

telegram = TelegramNotifier(db)

scheduler = TrackerScheduler(
    tracker,
    interval_seconds=config.scrape_interval_seconds,
    alert_callback=telegram.send_candidate,
)


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Start and stop the background tracker scheduler with FastAPI.
    """
    logger.info("Starting HMT Watch Tracker")

    scheduler.start(
        run_immediately=config.run_on_startup,
    )

    yield

    logger.info("Stopping HMT Watch Tracker")

    scheduler.stop()


app = FastAPI(
    title="HMT Watch Tracker",
    description="HMT Watches stock monitoring and Telegram alert system",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, Any]:
    """
    Lightweight health endpoint for deployment/platform checks.
    """
    return {
        "status": "ok",
        "service": "hmt-watch-tracker",
        "scheduler_running": scheduler.running,
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
        },
    )

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

@app.get("/api/status")
def api_status() -> dict[str, Any]:
    """Return overall application status in a dashboard-friendly shape."""
    scheduler_status = scheduler.status()
    last_run_at = scheduler_status.get("last_run_at")

    last_run = None
    next_run = None

    if last_run_at is not None:
        last_run_dt = datetime.fromtimestamp(
            float(last_run_at),
            tz=timezone.utc,
        )
        last_run = last_run_dt.isoformat()
        next_run_dt = last_run_dt.timestamp() + float(
            scheduler_status["interval_seconds"]
        )
        next_run = datetime.fromtimestamp(
            next_run_dt,
            tz=timezone.utc,
        ).isoformat()

    running = bool(scheduler_status.get("running"))

    return {
        "scheduler": scheduler_status,
        "scheduler_running": running,
        "running": running,
        "last_run": last_run,
        "last_completed_run": last_run,
        "last_run_at": last_run,
        "next_run": next_run,
        "telegram": {
            "enabled": telegram.enabled,
        },
        "database": db.get_stats(),
    }


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

@app.get("/api/watches")
def api_watches(
    source: str | None = None,
    in_stock: bool | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """
    Return catalogue watches.

    Filtering is intentionally basic at this stage. The full catalogue
    UI and richer filters will be added separately.
    """
    watches = db.get_watches(
        source=source,
        in_stock=in_stock,
        limit=limit,
        offset=offset,
    )

    if search:
        query = search.lower().strip()

        watches = [
            watch
            for watch in watches
            if query in watch.name.lower()
            or query in (watch.model_number or "").lower()
            or query in (watch.sku or "").lower()
        ]

    return {
        "count": len(watches),
        "limit": limit,
        "offset": offset,
        "watches": [
            watch.to_dict()
            for watch in watches
        ],
    }


@app.get("/api/watches/{watch_id:path}")
def api_watch(watch_id: str) -> dict[str, Any]:
    """
    Return one catalogue watch.
    """
    watch = db.get_watch(watch_id)

    if watch is None:
        raise HTTPException(
            status_code=404,
            detail="Watch not found",
        )

    return watch.to_dict()


# ---------------------------------------------------------------------------
# Tracking rules
# ---------------------------------------------------------------------------

@app.get("/api/tracking")
def api_tracking_rules() -> dict[str, Any]:
    """
    Return configured tracking rules.
    """
    rules = db.get_tracking_rules()

    return {
        "count": len(rules),
        "rules": [
            asdict(rule)
            for rule in rules
        ],
    }


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@app.get("/api/alerts")
def api_alerts(
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    """
    Return alert history.
    """
    alerts = db.get_alerts(
        status=status,
        limit=limit,
    )

    return {
        "count": len(alerts),
        "alerts": alerts,
    }


@app.get("/api/alerts/pending/count")
def api_pending_alert_count() -> dict[str, int]:
    """
    Return number of alerts waiting for Telegram delivery.
    """
    return {
        "count": db.get_stats().get(
            "pending_alert_count",
            0,
        )
    }


@app.post("/api/alerts/retry")
def api_retry_alerts(
    status: str = Query(
        default="failed",
        pattern="^(failed|pending)$",
    ),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """
    Retry failed or pending Telegram alerts.
    """
    if not telegram.enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "Telegram is not configured. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
            ),
        )

    try:
        if status == "failed":
            result = telegram.retry_failed_alerts(
                limit=limit,
            )
        else:
            result = telegram.retry_pending_alerts(
                limit=limit,
            )

    except Exception as exc:
        logger.exception("Alert retry failed")

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    return result


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

@app.post("/api/telegram/test")
def api_test_telegram() -> dict[str, Any]:
    """
    Send a Telegram test message.
    """
    if not telegram.enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "Telegram is not configured. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
            ),
        )

    try:
        result = telegram.test_send()

    except Exception as exc:
        logger.exception("Telegram test failed")

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    return {
        "success": True,
        "telegram": result,
    }


# ---------------------------------------------------------------------------
# Source status
# ---------------------------------------------------------------------------

@app.get("/api/sources")
def api_sources() -> dict[str, Any]:
    """
    Return status for all configured sources.
    """
    sources = []

    for source in config.sources:
        status = db.get_source_status(source.name)

        sources.append(
            {
                "name": source.name,
                "base_url": source.base_url,
                "configured_enabled": source.enabled,
                "database_enabled": db.is_source_enabled(
                    source.name,
                ),
                "status": status,
            }
        )

    return {
        "sources": sources,
    }


@app.post("/api/sources/{source_name}/enable")
def api_enable_source(source_name: str) -> dict[str, Any]:
    """
    Enable a source in the database.
    """
    source = config.get_source(source_name)

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Unknown source",
        )

    db.set_source_enabled(
        source_name,
        True,
    )

    return {
        "source": source_name,
        "enabled": True,
    }


@app.post("/api/sources/{source_name}/disable")
def api_disable_source(source_name: str) -> dict[str, Any]:
    """
    Disable a source in the database.
    """
    source = config.get_source(source_name)

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Unknown source",
        )

    db.set_source_enabled(
        source_name,
        False,
    )

    return {
        "source": source_name,
        "enabled": False,
    }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@app.get("/api/config")
def api_config() -> dict[str, Any]:
    """
    Return safe, non-secret application configuration.

    Telegram bot token is deliberately never exposed.
    """
    return {
        "scheduler_interval_seconds": (
            config.scrape_interval_seconds
        ),
        "scheduler_startup_run": (
            config.run_on_startup
        ),
        "http_timeout": config.request_timeout_seconds,
        "http_retries":config.request_retries,
        "alerts": {
            "seed_silently": config.seed_catalogue_silently,
            "new_products_only": config.alert_new_products_only,
            "only_when_in_stock": config.alert_only_when_in_stock,
            "back_in_stock": config.alert_back_in_stock,
            "out_of_stock": config.alert_out_of_stock,
            "price_changes": config.alert_price_changes,
        },
        "telegram": {
            "configured": telegram.enabled,
            "chat_id_configured": bool(
                config.telegram.chat_id
            ),
        },
        "sources": [
            {
                "name": source.name,
                "base_url": source.base_url,
                "enabled": source.enabled,
            }
            for source in config.sources
        ],
    }


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def api_stats() -> dict[str, Any]:
    """Return dashboard statistics using UI-compatible field names."""
    stats = db.get_stats()
    rules = db.get_tracking_rules()
    pending_alerts = db.get_alerts(
        status="pending",
        limit=1000,
    )

    return {
        **stats,
        "tracked": sum(1 for rule in rules if rule.enabled),
        "pending_alerts": len(pending_alerts),
    }
