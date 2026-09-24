from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from models import AlertState, TrackingRule, Watch, utc_now


class Database:
    """
    SQLite persistence layer for the HMT watch tracker.

    Responsibilities:
    - catalogue watches
    - tracking rules
    - Telegram alert state
    - alert history
    - scrape/run history
    - source status

    Scrapers and application code should use this class instead of
    accessing SQLite directly.
    """

    def __init__(self, path: str | Path = "data/hmt_tracker.db") -> None:
        self.path = Path(path)

        if self.path != Path(":memory:"):
            self.path.parent.mkdir(parents=True, exist_ok=True)

        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """
        Open a SQLite connection.

        Each operation gets its own connection. This works well with
        FastAPI and the background scheduler because connections are not
        shared between threads.
        """
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            check_same_thread=False,
        )

        connection.row_factory = sqlite3.Row

        # Foreign keys are disabled by default in SQLite.
        connection.execute("PRAGMA foreign_keys = ON")

        # WAL allows readers and writers to coexist more reliably.
        connection.execute("PRAGMA journal_mode = WAL")

        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        """Create all required database tables and indexes."""

        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS watches (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,

                    name TEXT NOT NULL,
                    model_number TEXT,
                    sku TEXT,

                    price REAL,
                    mrp REAL,

                    product_url TEXT NOT NULL,
                    image_url TEXT,

                    in_stock INTEGER NOT NULL DEFAULT 0,
                    stock_count INTEGER,

                    category TEXT,
                    collection TEXT,
                    gender TEXT,

                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    last_stock_check TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_watches_source
                    ON watches(source);

                CREATE INDEX IF NOT EXISTS idx_watches_name
                    ON watches(name);

                CREATE INDEX IF NOT EXISTS idx_watches_stock
                    ON watches(in_stock);

                CREATE TABLE IF NOT EXISTS tracking_rules (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,

                    source TEXT,

                    include_keywords TEXT,
                    exclude_keywords TEXT,
                    product_ids TEXT,

                    minimum_stock INTEGER NOT NULL DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_tracking_rules_enabled
                    ON tracking_rules(enabled);

                CREATE TABLE IF NOT EXISTS alert_states (
                    watch_id TEXT PRIMARY KEY,

                    first_alerted_at TEXT,
                    last_alerted_at TEXT,

                    alert_count INTEGER NOT NULL DEFAULT 0,

                    FOREIGN KEY(watch_id)
                        REFERENCES watches(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    watch_id TEXT NOT NULL,
                    source TEXT NOT NULL,

                    alert_type TEXT NOT NULL,

                    name TEXT NOT NULL,
                    stock_count INTEGER,

                    price REAL,
                    product_url TEXT,

                    status TEXT NOT NULL DEFAULT 'pending',

                    telegram_chat_id TEXT,
                    telegram_message_id TEXT,

                    error TEXT,

                    created_at TEXT NOT NULL,
                    sent_at TEXT,

                    FOREIGN KEY(watch_id)
                        REFERENCES watches(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_alerts_watch
                    ON alerts(watch_id);

                CREATE INDEX IF NOT EXISTS idx_alerts_status
                    ON alerts(status);

                CREATE INDEX IF NOT EXISTS idx_alerts_created
                    ON alerts(created_at);

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS stock_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_id TEXT NOT NULL,
                    in_stock INTEGER NOT NULL,
                    stock_count INTEGER,
                    observed_at TEXT NOT NULL,

                    FOREIGN KEY(watch_id)
                        REFERENCES watches(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_stock_events_watch
                    ON stock_events(watch_id, observed_at DESC);

                CREATE INDEX IF NOT EXISTS idx_stock_events_available
                    ON stock_events(watch_id, in_stock, observed_at DESC);

                -- Existing databases predate stock_events. Seed one
                -- baseline observation per watch so history is immediately
                -- useful after upgrading.
                INSERT INTO stock_events (
                    watch_id,
                    in_stock,
                    stock_count,
                    observed_at
                )
                SELECT
                    w.id,
                    w.in_stock,
                    w.stock_count,
                    w.last_stock_check
                FROM watches AS w
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM stock_events AS se
                    WHERE se.watch_id = w.id
                );

                CREATE TABLE IF NOT EXISTS scrape_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    started_at TEXT NOT NULL,
                    finished_at TEXT,

                    status TEXT NOT NULL,

                    total_found INTEGER NOT NULL DEFAULT 0,
                    new_products INTEGER NOT NULL DEFAULT 0,

                    in_stock INTEGER NOT NULL DEFAULT 0,
                    alerts_created INTEGER NOT NULL DEFAULT 0,
                    alerts_sent INTEGER NOT NULL DEFAULT 0,

                    error TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_scrape_runs_started
                    ON scrape_runs(started_at);

                CREATE TABLE IF NOT EXISTS source_status (
                    source TEXT PRIMARY KEY,

                    enabled INTEGER NOT NULL DEFAULT 1,

                    last_success TEXT,
                    last_failure TEXT,

                    last_error TEXT,

                    products_found INTEGER NOT NULL DEFAULT 0,

                    updated_at TEXT NOT NULL
                );
                """
            )

    # ------------------------------------------------------------------
    # Watches / catalogue
    # ------------------------------------------------------------------

    def get_watch(self, watch_id: str) -> Watch | None:
        """Return one catalogue watch by stable ID."""

        with self.connection() as db:
            row = db.execute(
                """
                SELECT *
                FROM watches
                WHERE id = ?
                """,
                (watch_id,),
            ).fetchone()

        if row is None:
            return None

        return self._watch_from_row(row)

    def watch_exists(self, watch_id: str) -> bool:
        """Return True if a watch already exists in the catalogue."""

        with self.connection() as db:
            row = db.execute(
                """
                SELECT 1
                FROM watches
                WHERE id = ?
                LIMIT 1
                """,
                (watch_id,),
            ).fetchone()

        return row is not None

    def get_watches(
        self,
        *,
        source: str | None = None,
        in_stock: bool | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Watch]:
        """
        Return catalogue watches with optional filtering.

        Search covers name, model number and SKU.
        """

        query = """
            SELECT *
            FROM watches
            WHERE 1 = 1
        """

        parameters: list[Any] = []

        if source:
            query += " AND source = ?"
            parameters.append(source)

        if in_stock is not None:
            query += " AND in_stock = ?"
            parameters.append(1 if in_stock else 0)

        if search:
            query += """
                AND (
                    name LIKE ?
                    OR model_number LIKE ?
                    OR sku LIKE ?
                )
            """

            search_value = f"%{search}%"
            parameters.extend(
                [
                    search_value,
                    search_value,
                    search_value,
                ]
            )

        query += """
            ORDER BY
                in_stock DESC,
                name COLLATE NOCASE ASC
        """

        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            parameters.extend([limit, offset])

        with self.connection() as db:
            rows = db.execute(query, parameters).fetchall()

        return [self._watch_from_row(row) for row in rows]

    def count_watches(
        self,
        *,
        source: str | None = None,
        in_stock: bool | None = None,
    ) -> int:
        """Return the number of catalogue watches matching filters."""

        query = """
            SELECT COUNT(*)
            FROM watches
            WHERE 1 = 1
        """

        parameters: list[Any] = []

        if source:
            query += " AND source = ?"
            parameters.append(source)

        if in_stock is not None:
            query += " AND in_stock = ?"
            parameters.append(1 if in_stock else 0)

        with self.connection() as db:
            return int(db.execute(query, parameters).fetchone()[0])

    def save_watch(self, watch: Watch) -> bool:
        """
        Insert or update a catalogue watch.

        Returns:
            True  -> newly inserted
            False -> existing watch updated
        """

        with self.connection() as db:
            existing = db.execute(
                """
                SELECT 1
                FROM watches
                WHERE id = ?
                """,
                (watch.id,),
            ).fetchone()

            if existing is None:
                db.execute(
                    """
                    INSERT INTO watches (
                        id,
                        source,
                        name,
                        model_number,
                        sku,
                        price,
                        mrp,
                        product_url,
                        image_url,
                        in_stock,
                        stock_count,
                        category,
                        collection,
                        gender,
                        first_seen,
                        last_seen,
                        last_stock_check
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?
                    )
                    """,
                    self._watch_values(watch),
                )

                return True

            db.execute(
                """
                UPDATE watches
                SET
                    source = ?,
                    name = ?,
                    model_number = COALESCE(?, model_number),
                    sku = COALESCE(?, sku),
                    price = COALESCE(?, price),
                    mrp = COALESCE(?, mrp),
                    product_url = ?,
                    image_url = COALESCE(?, image_url),
                    in_stock = ?,
                    stock_count = ?,
                    category = COALESCE(?, category),
                    collection = COALESCE(?, collection),
                    gender = COALESCE(?, gender),
                    last_seen = ?,
                    last_stock_check = ?
                WHERE id = ?
                """,
                (
                    watch.source,
                    watch.name,
                    watch.model_number,
                    watch.sku,
                    watch.price,
                    watch.mrp,
                    watch.product_url,
                    watch.image_url,
                    int(watch.in_stock),
                    watch.stock_count,
                    watch.category,
                    watch.collection,
                    watch.gender,
                    watch.last_seen,
                    watch.last_stock_check,
                    watch.id,
                ),
            )

        return False

    def save_watches(self, watches: list[Watch]) -> int:
        """
        Save multiple watches.

        Returns the number of newly inserted catalogue records.
        """

        new_count = 0

        with self.connection() as db:
            for watch in watches:
                existing = db.execute(
                    """
                    SELECT 1
                    FROM watches
                    WHERE id = ?
                    """,
                    (watch.id,),
                ).fetchone()

                if existing is None:
                    db.execute(
                        """
                        INSERT INTO watches (
                            id,
                            source,
                            name,
                            model_number,
                            sku,
                            price,
                            mrp,
                            product_url,
                            image_url,
                            in_stock,
                            stock_count,
                            category,
                            collection,
                            gender,
                            first_seen,
                            last_seen,
                            last_stock_check
                        )
                        VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?
                        )
                        """,
                        self._watch_values(watch),
                    )

                    new_count += 1
                    continue

                db.execute(
                    """
                    UPDATE watches
                    SET
                        source = ?,
                        name = ?,
                        model_number = COALESCE(?, model_number),
                        sku = COALESCE(?, sku),
                        price = COALESCE(?, price),
                        mrp = COALESCE(?, mrp),
                        product_url = ?,
                        image_url = COALESCE(?, image_url),
                        in_stock = ?,
                        stock_count = ?,
                        category = COALESCE(?, category),
                        collection = COALESCE(?, collection),
                        gender = COALESCE(?, gender),
                        last_seen = ?,
                        last_stock_check = ?
                    WHERE id = ?
                    """,
                    (
                        watch.source,
                        watch.name,
                        watch.model_number,
                        watch.sku,
                        watch.price,
                        watch.mrp,
                        watch.product_url,
                        watch.image_url,
                        int(watch.in_stock),
                        watch.stock_count,
                        watch.category,
                        watch.collection,
                        watch.gender,
                        watch.last_seen,
                        watch.last_stock_check,
                        watch.id,
                    ),
                )

        return new_count

    # ------------------------------------------------------------------
    # Tracking rules
    # ------------------------------------------------------------------

    def get_tracking_rules(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[TrackingRule]:
        """Return configured tracking rules."""

        query = """
            SELECT *
            FROM tracking_rules
        """

        parameters: list[Any] = []

        if enabled_only:
            query += " WHERE enabled = 1"

        query += " ORDER BY name COLLATE NOCASE ASC"

        with self.connection() as db:
            rows = db.execute(query, parameters).fetchall()

        return [self._rule_from_row(row) for row in rows]

    def get_tracking_rule(self, rule_id: str) -> TrackingRule | None:
        """Return one tracking rule."""

        with self.connection() as db:
            row = db.execute(
                """
                SELECT *
                FROM tracking_rules
                WHERE id = ?
                """,
                (rule_id,),
            ).fetchone()

        if row is None:
            return None

        return self._rule_from_row(row)

    def save_tracking_rule(self, rule: TrackingRule) -> None:
        """Insert or replace a tracking rule."""

        with self.connection() as db:
            db.execute(
                """
                INSERT INTO tracking_rules (
                    id,
                    name,
                    enabled,
                    source,
                    include_keywords,
                    exclude_keywords,
                    product_ids,
                    minimum_stock
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    enabled = excluded.enabled,
                    source = excluded.source,
                    include_keywords = excluded.include_keywords,
                    exclude_keywords = excluded.exclude_keywords,
                    product_ids = excluded.product_ids,
                    minimum_stock = excluded.minimum_stock
                """,
                (
                    rule.id,
                    rule.name,
                    int(rule.enabled),
                    rule.source,
                    self._json_dumps(rule.include_keywords),
                    self._json_dumps(rule.exclude_keywords),
                    self._json_dumps(rule.product_ids),
                    rule.minimum_stock,
                ),
            )

    def delete_tracking_rule(self, rule_id: str) -> bool:
        """Delete a tracking rule and return whether it existed."""

        with self.connection() as db:
            cursor = db.execute(
                """
                DELETE FROM tracking_rules
                WHERE id = ?
                """,
                (rule_id,),
            )

        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Alert state
    # ------------------------------------------------------------------

    def get_alert_state(self, watch_id: str) -> AlertState | None:
        """Return duplicate-alert state for a watch."""

        with self.connection() as db:
            row = db.execute(
                """
                SELECT *
                FROM alert_states
                WHERE watch_id = ?
                """,
                (watch_id,),
            ).fetchone()

        if row is None:
            return None

        return AlertState(
            watch_id=row["watch_id"],
            first_alerted_at=row["first_alerted_at"],
            last_alerted_at=row["last_alerted_at"],
            alert_count=int(row["alert_count"]),
        )

    def save_alert_state(self, state: AlertState) -> None:
        """Insert or update alert state."""

        with self.connection() as db:
            db.execute(
                """
                INSERT INTO alert_states (
                    watch_id,
                    first_alerted_at,
                    last_alerted_at,
                    alert_count
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(watch_id) DO UPDATE SET
                    first_alerted_at = excluded.first_alerted_at,
                    last_alerted_at = excluded.last_alerted_at,
                    alert_count = excluded.alert_count
                """,
                (
                    state.watch_id,
                    state.first_alerted_at,
                    state.last_alerted_at,
                    state.alert_count,
                ),
            )

    # ------------------------------------------------------------------
    # Alert history
    # ------------------------------------------------------------------

    def create_alert(
        self,
        *,
        watch: Watch,
        alert_type: str,
        status: str = "pending",
        telegram_chat_id: str | None = None,
        error: str | None = None,
    ) -> int:
        """
        Create an alert history record.

        The actual Telegram send happens elsewhere.
        """

        with self.connection() as db:
            cursor = db.execute(
                """
                INSERT INTO alerts (
                    watch_id,
                    source,
                    alert_type,
                    name,
                    stock_count,
                    price,
                    product_url,
                    status,
                    telegram_chat_id,
                    error,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    watch.id,
                    watch.source,
                    alert_type,
                    watch.name,
                    watch.stock_count,
                    watch.price,
                    watch.product_url,
                    status,
                    telegram_chat_id,
                    error,
                    utc_now(),
                ),
            )

            return int(cursor.lastrowid)

    def mark_alert_sent(
        self,
        alert_id: int,
        *,
        telegram_message_id: str | None = None,
    ) -> None:
        """Mark an alert as successfully delivered."""

        with self.connection() as db:
            db.execute(
                """
                UPDATE alerts
                SET
                    status = 'sent',
                    telegram_message_id = ?,
                    sent_at = ?,
                    error = NULL
                WHERE id = ?
                """,
                (
                    telegram_message_id,
                    utc_now(),
                    alert_id,
                ),
            )

    def mark_alert_failed(
        self,
        alert_id: int,
        error: str,
    ) -> None:
        """Mark an alert as failed while preserving it for retry."""

        with self.connection() as db:
            db.execute(
                """
                UPDATE alerts
                SET
                    status = 'failed',
                    error = ?
                WHERE id = ?
                """,
                (
                    error,
                    alert_id,
                ),
            )

    def get_alerts(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return recent alert history for the UI."""

        query = """
            SELECT *
            FROM alerts
        """

        parameters: list[Any] = []

        if status:
            query += " WHERE status = ?"
            parameters.append(status)

        query += """
            ORDER BY created_at DESC
            LIMIT ?
        """

        parameters.append(limit)

        with self.connection() as db:
            rows = db.execute(query, parameters).fetchall()

        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Stock availability history
    # ------------------------------------------------------------------

    def record_stock_event(
        self,
        watch: Watch,
        *,
        observed_at: str | None = None,
    ) -> None:
        """Record a stock-state transition for a watch."""
        timestamp = observed_at or watch.last_stock_check or utc_now()

        with self.connection() as db:
            db.execute(
                """
                INSERT INTO stock_events (
                    watch_id,
                    in_stock,
                    stock_count,
                    observed_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    watch.id,
                    int(watch.in_stock),
                    watch.stock_count,
                    timestamp,
                ),
            )

    def get_stock_events(
        self,
        watch_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return stock-state changes for a watch, newest first."""
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT id, watch_id, in_stock, stock_count, observed_at
                FROM stock_events
                WHERE watch_id = ?
                ORDER BY observed_at DESC, id DESC
                LIMIT ?
                """,
                (watch_id, limit),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_last_stock_event(
        self,
        watch_id: str,
    ) -> dict[str, Any] | None:
        """Return the newest stock-state event for a watch."""
        with self.connection() as db:
            row = db.execute(
                """
                SELECT id, watch_id, in_stock, stock_count, observed_at
                FROM stock_events
                WHERE watch_id = ?
                ORDER BY observed_at DESC, id DESC
                LIMIT 1
                """,
                (watch_id,),
            ).fetchone()

        return dict(row) if row else None

    def get_watch_history_summary(
        self,
        watch_id: str,
    ) -> dict[str, Any]:
        """Return availability and alert history summary for one watch."""
        with self.connection() as db:
            last_available = db.execute(
                """
                SELECT observed_at
                FROM stock_events
                WHERE watch_id = ? AND in_stock = 1
                ORDER BY observed_at DESC, id DESC
                LIMIT 1
                """,
                (watch_id,),
            ).fetchone()

            last_alerted = db.execute(
                """
                SELECT MAX(COALESCE(sent_at, created_at)) AS last_alerted_at
                FROM alerts
                WHERE watch_id = ? AND status = 'sent'
                """,
                (watch_id,),
            ).fetchone()

            alert_count = db.execute(
                """
                SELECT COUNT(*) AS count
                FROM alerts
                WHERE watch_id = ? AND status = 'sent'
                """,
                (watch_id,),
            ).fetchone()

        return {
            "last_available_at": (
                last_available["observed_at"] if last_available else None
            ),
            "last_alerted_at": (
                last_alerted["last_alerted_at"] if last_alerted else None
            ),
            "alert_count": int(alert_count["count"] if alert_count else 0),
        }

    # ------------------------------------------------------------------
    # Scrape runs
    # ------------------------------------------------------------------

    def start_scrape_run(self) -> int:
        """Create a running scrape record."""

        with self.connection() as db:
            cursor = db.execute(
                """
                INSERT INTO scrape_runs (
                    started_at,
                    status
                )
                VALUES (?, 'running')
                """,
                (utc_now(),),
            )

            return int(cursor.lastrowid)

    def finish_scrape_run(
        self,
        run_id: int,
        *,
        status: str,
        total_found: int = 0,
        new_products: int = 0,
        in_stock: int = 0,
        alerts_created: int = 0,
        alerts_sent: int = 0,
        error: str | None = None,
    ) -> None:
        """Complete a scrape-run record."""

        with self.connection() as db:
            db.execute(
                """
                UPDATE scrape_runs
                SET
                    finished_at = ?,
                    status = ?,
                    total_found = ?,
                    new_products = ?,
                    in_stock = ?,
                    alerts_created = ?,
                    alerts_sent = ?,
                    error = ?
                WHERE id = ?
                """,
                (
                    utc_now(),
                    status,
                    total_found,
                    new_products,
                    in_stock,
                    alerts_created,
                    alerts_sent,
                    error,
                    run_id,
                ),
            )

    def get_scrape_runs(
        self,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent scraper runs."""

        with self.connection() as db:
            rows = db.execute(
                """
                SELECT *
                FROM scrape_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Source status
    # ------------------------------------------------------------------

    def set_source_success(
        self,
        source: str,
        *,
        products_found: int,
    ) -> None:
        """Record a successful source scrape."""

        now = utc_now()

        with self.connection() as db:
            db.execute(
                """
                INSERT INTO source_status (
                    source,
                    enabled,
                    last_success,
                    last_failure,
                    last_error,
                    products_found,
                    updated_at
                )
                VALUES (?, 1, ?, NULL, NULL, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_success = excluded.last_success,
                    last_failure = NULL,
                    last_error = NULL,
                    products_found = excluded.products_found,
                    updated_at = excluded.updated_at
                """,
                (
                    source,
                    now,
                    products_found,
                    now,
                ),
            )

    def set_source_failure(
        self,
        source: str,
        *,
        error: str,
    ) -> None:
        """Record a failed source scrape."""

        now = utc_now()

        with self.connection() as db:
            db.execute(
                """
                INSERT INTO source_status (
                    source,
                    enabled,
                    last_failure,
                    last_error,
                    updated_at
                )
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_failure = excluded.last_failure,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    source,
                    now,
                    error,
                    now,
                ),
            )

    def get_source_status(
        self,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return source health information."""

        query = """
            SELECT *
            FROM source_status
        """

        parameters: list[Any] = []

        if source:
            query += " WHERE source = ?"
            parameters.append(source)

        query += " ORDER BY source"

        with self.connection() as db:
            rows = db.execute(query, parameters).fetchall()

        return [dict(row) for row in rows]

    def set_source_enabled(
        self,
        source: str,
        enabled: bool,
    ) -> None:
        """Enable or disable a source."""

        now = utc_now()

        with self.connection() as db:
            db.execute(
                """
                INSERT INTO source_status (
                    source,
                    enabled,
                    updated_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    source,
                    int(enabled),
                    now,
                ),
            )

    def is_source_enabled(self, source: str) -> bool:
        """Return whether a source is enabled."""

        with self.connection() as db:
            row = db.execute(
                """
                SELECT enabled
                FROM source_status
                WHERE source = ?
                """,
                (source,),
            ).fetchone()

        # New sources are enabled by default.
        if row is None:
            return True

        return bool(row["enabled"])

    # ------------------------------------------------------------------
    # Dashboard statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, int]:
        """Return basic dashboard catalogue statistics."""

        with self.connection() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM watches"
            ).fetchone()[0]

            in_stock = db.execute(
                """
                SELECT COUNT(*)
                FROM watches
                WHERE in_stock = 1
                """
            ).fetchone()[0]

            sources = db.execute(
                """
                SELECT COUNT(DISTINCT source)
                FROM watches
                """
            ).fetchone()[0]

            alerts = db.execute(
                """
                SELECT COUNT(*)
                FROM alerts
                WHERE status = 'sent'
                """
            ).fetchone()[0]

            failed_alerts = db.execute(
                """
                SELECT COUNT(*)
                FROM alerts
                WHERE status = 'failed'
                """
            ).fetchone()[0]

        return {
            "total_watches": int(total),
            "in_stock": int(in_stock),
            "sources": int(sources),
            "alerts_sent": int(alerts),
            "failed_alerts": int(failed_alerts),
        }

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _watch_values(watch: Watch) -> tuple[Any, ...]:
        """Return database values for a Watch."""

        return (
            watch.id,
            watch.source,
            watch.name,
            watch.model_number,
            watch.sku,
            watch.price,
            watch.mrp,
            watch.product_url,
            watch.image_url,
            int(watch.in_stock),
            watch.stock_count,
            watch.category,
            watch.collection,
            watch.gender,
            watch.first_seen,
            watch.last_seen,
            watch.last_stock_check,
        )

    @staticmethod
    def _watch_from_row(row: sqlite3.Row) -> Watch:
        """Convert a SQLite row into a Watch."""

        return Watch(
            id=row["id"],
            source=row["source"],
            name=row["name"],
            model_number=row["model_number"],
            sku=row["sku"],
            price=row["price"],
            mrp=row["mrp"],
            product_url=row["product_url"],
            image_url=row["image_url"],
            in_stock=bool(row["in_stock"]),
            stock_count=row["stock_count"],
            category=row["category"],
            collection=row["collection"],
            gender=row["gender"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            last_stock_check=row["last_stock_check"],
        )

    @staticmethod
    def _rule_from_row(row: sqlite3.Row) -> TrackingRule:
        """Convert a SQLite row into a TrackingRule."""

        return TrackingRule(
            id=row["id"],
            name=row["name"],
            enabled=bool(row["enabled"]),
            source=row["source"],
            include_keywords=Database._json_loads(row["include_keywords"]),
            exclude_keywords=Database._json_loads(row["exclude_keywords"]),
            product_ids=Database._json_loads(row["product_ids"]),
            minimum_stock=int(row["minimum_stock"]),
        )

    @staticmethod
    def _json_dumps(value: Any) -> str | None:
        """Serialize optional lists for SQLite."""

        if value is None:
            return None

        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _json_loads(value: str | None) -> Any:
        """Deserialize optional JSON values safely."""

        if not value:
            return None

        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return None

    # ------------------------------------------------------------------
    # Application settings
    # ------------------------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Return a persisted application setting, or the supplied default."""
        with self.connection() as db:
            row = db.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()

        if row is None:
            return default

        return str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        """Persist an application setting."""
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, str(value), utc_now()),
            )

    def get_settings(self, keys: list[str] | None = None) -> dict[str, str]:
        """Return persisted application settings, optionally limited to keys."""
        with self.connection() as db:
            if keys:
                placeholders = ",".join("?" for _ in keys)
                rows = db.execute(
                    f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})",
                    tuple(keys),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT key, value FROM app_settings"
                ).fetchall()

        return {str(row["key"]): str(row["value"]) for row in rows}

