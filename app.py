from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import config
from database import Database
from models import TrackingRule
from notifier import TelegramNotifier
from scheduler import TrackerScheduler
from tracker import Tracker


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("hmt-tracker")


# ---------------------------------------------------------------------------
# Application services
# ---------------------------------------------------------------------------

db = Database(config.database_path)

tracker = Tracker(
    db,
    tracker_config=config,
)

telegram = TelegramNotifier(
    db,
)

scheduler = TrackerScheduler(
    tracker,
    interval_seconds=config.scrape_interval_seconds,
    alert_callback=telegram.send_candidate,
)


# ---------------------------------------------------------------------------
# Templates / application
# ---------------------------------------------------------------------------

templates = Jinja2Templates(
    directory="templates",
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
# Static files
# ---------------------------------------------------------------------------

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_iso_from_timestamp(
    timestamp: float | int | None,
) -> str | None:
    """
    Convert a Unix timestamp into an ISO-8601 UTC string.
    """
    if timestamp is None:
        return None

    return datetime.fromtimestamp(
        float(timestamp),
        tz=timezone.utc,
    ).isoformat()


def _normalise_list(
    value: Any,
    *,
    field_name: str,
) -> list[str]:
    """
    Convert a UI/API value into a clean list of strings.

    Accepted input:
      - None
      - a list/tuple/set
      - a comma-separated string
      - a newline-separated string
    """
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    elif isinstance(value, str):
        raw_values = value.replace(
            "\r",
            "",
        ).replace(
            ",",
            "\n",
        ).split("\n")
    else:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be a list or string.",
        )

    result: list[str] = []

    for item in raw_values:
        text = str(item).strip()

        if text and text not in result:
            result.append(text)

    return result


def _parse_tracking_rule(
    payload: dict[str, Any],
    *,
    rule_id: str | None = None,
) -> TrackingRule:
    """
    Validate and convert an API payload into a TrackingRule.
    """
    name = str(
        payload.get("name", ""),
    ).strip()

    if not name:
        raise HTTPException(
            status_code=422,
            detail="Tracking rule name is required.",
        )

    source = payload.get("source")

    if source is not None:
        source = str(source).strip()

        if source == "":
            source = None

    if source is not None:
        try:
            config.get_source(source)
        except KeyError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown source: {source}",
            ) from exc

    enabled_value = payload.get(
        "enabled",
        True,
    )

    if isinstance(enabled_value, str):
        enabled = enabled_value.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    else:
        enabled = bool(enabled_value)

    try:
        minimum_stock = int(
            payload.get(
                "minimum_stock",
                0,
            )
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="minimum_stock must be a non-negative integer.",
        ) from exc

    if minimum_stock < 0:
        raise HTTPException(
            status_code=422,
            detail="minimum_stock cannot be negative.",
        )

    include_keywords = _normalise_list(
        payload.get("include_keywords"),
        field_name="include_keywords",
    )

    exclude_keywords = _normalise_list(
        payload.get("exclude_keywords"),
        field_name="exclude_keywords",
    )

    product_ids = _normalise_list(
        payload.get("product_ids"),
        field_name="product_ids",
    )

    final_id = (
        rule_id
        or str(payload.get("id", "")).strip()
        or uuid.uuid4().hex
    )

    return TrackingRule(
        id=final_id,
        name=name,
        enabled=enabled,
        source=source,
        include_keywords=include_keywords,
        exclude_keywords=exclude_keywords,
        product_ids=product_ids,
        minimum_stock=minimum_stock,
    )


def _rule_to_dict(
    rule: TrackingRule,
) -> dict[str, Any]:
    """
    Convert a TrackingRule into JSON-compatible data.
    """
    return asdict(rule)


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
# HTML pages
# ---------------------------------------------------------------------------

@app.get(
    "/",
    response_class=HTMLResponse,
)
def dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
        },
    )


@app.get(
    "/catalogue",
    response_class=HTMLResponse,
)
def catalogue(request: Request):
    return templates.TemplateResponse(
        "catalogue.html",
        {
            "request": request,
        },
    )


@app.get(
    "/tracking",
    response_class=HTMLResponse,
)
def tracking_page(request: Request):
    return templates.TemplateResponse(
        "tracking.html",
        {
            "request": request,
        },
    )


@app.get(
    "/alerts",
    response_class=HTMLResponse,
)
def alerts_page(request: Request):
    return templates.TemplateResponse(
        "alerts.html",
        {
            "request": request,
        },
    )


@app.get(
    "/settings",
    response_class=HTMLResponse,
)
def settings_page(request: Request):
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
        },
    )


# ---------------------------------------------------------------------------
# Scheduler / tracker status
# ---------------------------------------------------------------------------

@app.get("/api/status")
def api_status() -> dict[str, Any]:
    """
    Return overall application status in a dashboard-friendly shape.
    """
    scheduler_status = scheduler.status()

    recent_runs = db.get_scrape_runs(limit=1)
    last_run_record = recent_runs[0] if recent_runs else None

    last_run = (
        last_run_record.get("finished_at")
        if last_run_record and last_run_record.get("finished_at")
        else None
    )

    last_run_at = scheduler_status.get(
        "last_run_at",
    )

    next_run = None

    if last_run_at is not None:
        next_run_timestamp = (
            float(last_run_at)
            + float(
                scheduler_status["interval_seconds"]
            )
        )

        next_run = _utc_iso_from_timestamp(
            next_run_timestamp,
        )

    running = bool(
        scheduler_status.get("running")
    )

    return {
        "scheduler": scheduler_status,
        "scheduler_running": running,
        "running": running,
        "status": (
            "running"
            if running
            else "stopped"
        ),
        "last_run": last_run,
        "last_completed_run": last_run,
        "last_run_at": last_run,
        "next_run": next_run,
        "last_run_record": last_run_record,
        "telegram": {
            "enabled": telegram.enabled,
        },
        "database": db.get_stats(),
    }


@app.post("/api/run")
def api_run_tracker() -> dict[str, Any]:
    """
    Execute one tracker run immediately.

    The Tracker itself prevents concurrent executions.
    """
    try:
        result = scheduler.run_now()

    except RuntimeError as exc:
        message = str(exc)
        if "already in progress" in message.lower():
            logger.warning("Manual tracker run rejected: %s", message)
            raise HTTPException(status_code=409, detail=message) from exc
        logger.exception("Manual tracker run failed with RuntimeError")
        raise HTTPException(status_code=500, detail=message) from exc

    except Exception as exc:
        logger.exception("Manual tracker run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "success": result.success,
        "run": {
            "run_id": result.run_id,
            "total_products": result.total_products,
            "new_products": result.new_products,
            "in_stock_products": result.in_stock_products,
            "alerts_created": result.alerts_created,
            "first_run_seed": result.first_run_seed,
            "error": result.error,
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
        },
    }


@app.get("/api/runs")
def api_runs(
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Return recent tracker run history from SQLite."""
    runs = db.get_scrape_runs(limit=limit)
    return {"count": len(runs), "runs": runs}


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

@app.get("/api/watches")
def api_watches(
    source: str | None = None,
    in_stock: bool | None = None,
    search: str | None = None,
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
) -> dict[str, Any]:
    """
    Return catalogue watches.

    Search is applied across:
      - name
      - model number
      - SKU
      - category
      - collection
      - gender
    """
    all_watches = db.get_watches(
        source=source,
        in_stock=in_stock,
        limit=100000,
        offset=0,
    )

    if search:
        query = search.strip().lower()

        if query:
            filtered = []

            for watch in all_watches:
                fields = (
                    watch.name,
                    watch.model_number or "",
                    watch.sku or "",
                    watch.category or "",
                    watch.collection or "",
                    watch.gender or "",
                )

                if any(
                    query in field.lower()
                    for field in fields
                ):
                    filtered.append(watch)

            all_watches = filtered

    total = len(all_watches)

    watches = all_watches[
        offset:offset + limit
    ]

    return {
        "count": total,
        "total": total,
        "limit": limit,
        "offset": offset,
        "watches": [
            watch.to_dict()
            for watch in watches
        ],
    }


@app.get("/api/watch-history")
def api_watch_history(
    search: str = Query(
        default="",
        max_length=200,
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
) -> dict[str, Any]:
    """
    Return availability and alert history for watches matching a model/name
    search. This is useful when one model exists at multiple sources.
    """
    watches = db.get_watches(
        search=search.strip() or None,
        limit=limit,
        offset=0,
    )

    items: list[dict[str, Any]] = []

    for watch in watches:
        history = db.get_watch_history_summary(watch.id)
        items.append(
            {
                **watch.to_dict(),
                **history,
            }
        )

    return {
        "count": len(items),
        "watches": items,
    }


@app.get("/api/watches/{watch_id:path}")
def api_watch(
    watch_id: str,
) -> dict[str, Any]:
    """
    Return one catalogue watch.
    """
    watch = db.get_watch(
        watch_id,
    )

    if watch is None:
        raise HTTPException(
            status_code=404,
            detail="Watch not found",
        )

    return {
        **watch.to_dict(),
        **db.get_watch_history_summary(watch.id),
    }


# ---------------------------------------------------------------------------
# Tracking rules
# ---------------------------------------------------------------------------

@app.get(
    "/api/tracking",
)
def api_tracking_rules() -> dict[str, Any]:
    """
    Return configured tracking rules.
    """
    rules = db.get_tracking_rules()

    return {
        "count": len(rules),
        "rules": [
            _rule_to_dict(rule)
            for rule in rules
        ],
    }


@app.post(
    "/api/tracking",
)
def api_create_tracking_rule(
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """
    Create a new tracking rule.
    """
    rule = _parse_tracking_rule(
        payload,
    )

    if db.get_tracking_rule(rule.id) is not None:
        rule = _parse_tracking_rule(
            payload,
            rule_id=uuid.uuid4().hex,
        )

    db.save_tracking_rule(
        rule,
    )

    # A newly created tracker must also evaluate watches that are already
    # in stock. Waiting for a stock transition would miss watches that were
    # already available when the user created the tracker.
    initial_alerts = tracker.activate_tracking_rule(
        rule,
        alert_callback=telegram.send_candidate,
    )

    return {
        "success": True,
        "rule": _rule_to_dict(rule),
        "initial_alerts_created": initial_alerts,
    }


@app.put(
    "/api/tracking/{rule_id}",
)
def api_update_tracking_rule(
    rule_id: str,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """
    Update an existing tracking rule.
    """
    existing = db.get_tracking_rule(
        rule_id,
    )

    if existing is None:
        raise HTTPException(
            status_code=404,
            detail="Tracking rule not found",
        )

    rule = _parse_tracking_rule(
        payload,
        rule_id=rule_id,
    )

    db.save_tracking_rule(
        rule,
    )

    return {
        "success": True,
        "rule": _rule_to_dict(rule),
    }


@app.delete(
    "/api/tracking/{rule_id}",
)
def api_delete_tracking_rule(
    rule_id: str,
) -> dict[str, Any]:
    """
    Delete an existing tracking rule.
    """
    deleted = db.delete_tracking_rule(
        rule_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Tracking rule not found",
        )

    return {
        "success": True,
        "deleted": rule_id,
    }


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@app.get("/api/alerts")
def api_alerts(
    status: str | None = None,
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
    ),
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
    pending = db.get_alerts(
        status="pending",
        limit=100000,
    )

    return {
        "count": len(pending),
    }


@app.post("/api/alerts/retry")
def api_retry_alerts(
    status: str = Query(
        default="failed",
        pattern="^(failed|pending)$",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
    ),
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
        logger.exception(
            "Alert retry failed",
        )

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
        logger.exception(
            "Telegram test failed",
        )

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
        status_rows = db.get_source_status(
            source.name,
        )

        database_enabled = db.is_source_enabled(
            source.name,
        )

        sources.append(
            {
                "name": source.name,
                "base_url": source.base_url,
                "configured_enabled": source.enabled,
                "database_enabled": database_enabled,
                "enabled": (
                    source.enabled
                    and database_enabled
                ),
                "status": (
                    status_rows[0]
                    if status_rows
                    else None
                ),
            }
        )

    return {
        "sources": sources,
    }


@app.post(
    "/api/sources/{source_name}/enable",
)
def api_enable_source(
    source_name: str,
) -> dict[str, Any]:
    """
    Enable a source in the database.
    """
    source = config.get_source(
        source_name,
    )

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


@app.post(
    "/api/sources/{source_name}/disable",
)
def api_disable_source(
    source_name: str,
) -> dict[str, Any]:
    """
    Disable a source in the database.
    """
    source = config.get_source(
        source_name,
    )

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

def _get_repeat_enabled() -> bool:
    value = db.get_setting(
        "alert_repeat_enabled",
        str(config.alert_repeat_enabled).lower(),
    )
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_repeat_interval_minutes() -> int:
    value = db.get_setting(
        "alert_repeat_interval_minutes",
        str(config.alert_repeat_interval_minutes),
    )
    try:
        return max(1, min(10080, int(value)))
    except (TypeError, ValueError):
        return max(1, min(10080, int(config.alert_repeat_interval_minutes)))


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
        "http_timeout": (
            config.request_timeout_seconds
        ),
        "http_retries": (
            config.request_retries
        ),
        "alerts": {
            "seed_silently": (
                config.seed_catalogue_silently
            ),
            "new_products_only": (
                config.alert_new_products_only
            ),
            "only_when_in_stock": (
                config.alert_only_when_in_stock
            ),
            "back_in_stock": (
                config.alert_back_in_stock
            ),
            "out_of_stock": (
                config.alert_out_of_stock
            ),
            "price_changes": (
                config.alert_price_changes
            ),
            "repeat_enabled": _get_repeat_enabled(),
            "repeat_interval_minutes": _get_repeat_interval_minutes(),
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


@app.put("/api/settings/repeat-alerts")
def update_repeat_alert_settings(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Update repeat-alert settings persisted in SQLite."""
    enabled = payload.get("enabled")
    interval = payload.get("interval_minutes")

    if not isinstance(enabled, bool):
        raise HTTPException(
            status_code=400,
            detail="enabled must be a boolean.",
        )

    try:
        interval_minutes = int(interval)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="interval_minutes must be an integer.",
        )

    if not 1 <= interval_minutes <= 10080:
        raise HTTPException(
            status_code=400,
            detail="interval_minutes must be between 1 and 10080 minutes.",
        )

    db.set_setting("alert_repeat_enabled", str(enabled).lower())
    db.set_setting("alert_repeat_interval_minutes", str(interval_minutes))

    return {
        "enabled": enabled,
        "interval_minutes": interval_minutes,
    }


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def api_stats() -> dict[str, Any]:
    """
    Return dashboard statistics.
    """
    stats = db.get_stats()

    rules = db.get_tracking_rules()

    pending_alerts = db.get_alerts(
        status="pending",
        limit=100000,
    )

    return {
        **stats,
        "tracked": sum(
            1
            for rule in rules
            if rule.enabled
        ),
        "pending_alerts": len(
            pending_alerts
        ),
    }