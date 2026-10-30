# Reliability update — 30 October 2026

## Findings

- The scheduler previously waited the configured interval AFTER a complete scrape and Telegram delivery. A 40-second execution plus a 60-second wait meant roughly 100 seconds between starts.
- Sources ran sequentially. A slow source delayed the other source.
- Official HMT's parser explicitly merged Coming Soon and Out of Stock.
- Telegram delivery ran synchronously inside product processing. Image fetching could block later watches; pending/failed alerts had no background delivery worker.
- HTTP failures were retried immediately, including denied/rate-limited requests.
- The store scraped all catalogue pages and ambiguous-stock detail pages before processing changes.
- The deployed read-only `/api/status` reported interval_seconds=60, scheduler running, and night_mode=true during this review. Night rest deliberately skips checks.
- A direct homepage request confirmed Coming Soon labels. The .store HTML page returned HTTP 403 from the review environment; this is not proof that the deployed server's IP is banned. The deployment's latest recorded run reported both sources successful.

## Priority-worker update

- Each source now has its own scheduler and execution lock. A slow source does not delay the next check on the other source.
- Startup and every 15 minutes perform catalogue discovery. Between these runs, only watches matching enabled tracking rules are committed and evaluated for alerts. Sources with no applicable rules skip priority requests.
- Priority cycles still fetch bulk catalogue pages because an efficient supported selected-ID batch endpoint has not been established. This is a processing optimization, not a promise of fewer catalogue HTTP requests. Ambiguous tracked products still require detail requests.
- `/api/status` now exposes per-source scheduler status/mode and per-host request counts, last HTTP status and cooldown seconds. Existing top-level fields remain for dashboard compatibility.
- Host request spacing defaults to 2–2.25 seconds and can be adjusted with HMT_MIN_REQUEST_INTERVAL_SECONDS (minimum 1 second). This is a local policy, not a verified HMT allowance.
- Numeric Telegram group destinations use at least 3.1 seconds between sends. HTTP 429 still triggers Telegram's requested cooldown.
- No automatic proxy/IP rotation was added. No supported rate limit or proxy pool was supplied; rate-limited hosts pause instead of continuing requests through another address.
- A live read-only store API check returned 100 products on its first page; 83 triggered the existing ambiguity rule. Consequently, fast accurate checks for 50 tracked products cannot be guaranteed from bulk data alone. Measure detail lookup time and successful freshness on the deployed server before lowering the interval.

## Implemented

1. Explicit availability: available, out_of_stock, coming_soon, unknown. Existing in_stock API field remains compatible. Back in stock and price changed remain events, not availability states.
2. Idempotent SQLite schema migration, including old boolean availability mapping. Existing rows and tracking rules retained. Unknown observations preserve an existing watch's last known stock and last successful stock-check timestamp, and do not generate stock alerts.
3. Coming Soon catalogue badge/filter and alert setting, enabled by default for matching tracking rules. The first scan after upgrade can send one Coming Soon notification per matching watch. Disable it before running if undesired.
4. Monotonic start-to-start scheduler cadence. Missed ticks are skipped, not replayed in bursts. Runs still never overlap. Night mode remains effective.
5. Two source tasks run concurrently. Store watches are persisted and notifications queued as pages arrive, instead of waiting for the complete catalogue.
6. Ambiguous store stock detail checks are limited to watches matching enabled tracking rules. Unverified observations are unknown, not assumed sold out.
7. Shared per-host request spacing (1–1.25 seconds), circuit cooldown on 403/429/5xx, Retry-After handling, and bounded retries for transient network errors. Policy persists across scraper instances in the running process. It resets on process restart; avoid restarting during a source cooldown.
8. Durable SQLite Telegram outbox, independent of scraping. Urgent new/tracked/back-in-stock alerts use text immediately; other types retain photo support. Stock events take priority over price/repeat events. Failed deliveries are retried with exponential delay, and Telegram flood-control Retry-After is honored.
9. Immutable watch snapshots attached to alerts. Retries describe the observed event rather than rewriting it from later stock state. Legacy alerts use their stored fields. Telegram acceptance does not prove the phone received a push notification.
10. Fixed failure-path keyword mismatch in Telegram retry handling, source session cleanup, run-lock cleanup on setup failure, and a pagination no-progress guard.

## Upgrade

1. Stop the existing application/container. Back up the live SQLite database and `.env`. Do not replace the live database with the historical backup bundled in the original source.
2. Replace application source with this archive, preserving the live `.env` and data volume. No new runtime dependencies were added.
3. Rebuild/restart using your existing deployment procedure. For Docker, retain the current environment and persistent `/app/data` mount. Do not start a second instance against the same database.
4. Use exactly ONE uvicorn worker, without `--reload`. Scheduler locks, host pacing and outbox ownership are process-local. Multi-worker/multi-replica operation requires distributed coordination and is not implemented here.
5. In Settings: set interval to one minute, disable night rest for continuous monitoring, enable Back in stock, and check tracking rules and the Coming soon toggle. Existing choices are retained; Back in stock is disabled by the original default unless enabled by the user.
6. Inspect `/api/status`, source results, scrape run timestamps, and alerts after restart. Source failures retain last known inventory; a cooldown means intentionally stale observations, not a successful fresh check.

## Timely fetching and remaining limits

Your code already fetches the site's catalogue endpoints. An IP pool cannot fix long scans, delayed processing, upstream caching, or notification queueing.

For tighter freshness, independent source workers now separate priority processing from 15-minute catalogue discovery. Set fast-worker frequency only after measuring the actual endpoint cost and agreeing an acceptable request rate with the provider. Multiple workers must share a host-wide budget. A selected-ID bulk endpoint remains unverified; priority workers still read catalogue pages.

At a 60-second healthy polling cadence, detection waits can approach a full minute, plus request/processing/Telegram/device delays. A product selling out between polls can be missed. If a full scan exceeds the interval, this patch skips ticks rather than overlapping scans. A very large tracked list can still produce expensive ambiguous-product detail checks and a Telegram backlog. Per-chat pacing limits throughput.

Official-site filter/all-product response coverage and live pagination still need verification against the current frontend; the latest deployment report contained only 36 official-site products, which does not establish complete catalogue coverage. This patch preserves the existing two official discovery endpoints and does not claim to fix their pagination or undocumented API changes.

If the source denies even a low, paced request rate, ask HMT for an authorized inventory feed, webhook, or an allowlisted API/static egress IP with an agreed rate. No such integration has been confirmed available. GET conditional requests can reduce bandwidth if a source supplies usable ETags, but they still count as requests; conditional caching was not added here.

## Validation

- `python -m pytest -q`: 56 passed, including 19 new regression cases.
- Covers Coming Soon precedence and persistence, legacy database migration, Coming Soon to available transitions, duplicate suppression, unknown stock preservation, source cooldowns, snapshot delivery, deferred retries, Telegram Retry-After, fixed scheduler cadence and missed ticks, store page streaming and pagination guard, and skipping untracked detail requests.
- `python -m compileall -q .` passed.
- Live read-only checks: tracker status and HMT homepage. No Telegram messages sent, production files changed, or deployment performed. End-to-end live stock detection and real Telegram delivery remain to be checked on your server after upgrade.
