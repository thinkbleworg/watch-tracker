# WhatsApp Channel integration (WAHA Core)

This upgrade adds a second, independent SQLite-backed notification worker for WhatsApp Channels. Your existing HMT scrapers, scheduler, Telegram notifier, alert filters and Telegram retry endpoints are unchanged. WhatsApp uses the same alert events. WAHA 2026.6.1 and later includes media for free; see the [release announcement](https://waha.devlike.pro/blog/waha-2026-6/) and [Channel API](https://waha.devlike.pro/docs/how-to/channels/).

**Read before deploying:** WAHA is an unofficial linked-device integration, not an officially authorized WhatsApp Channel API. Your only WhatsApp number will be linked to the server, with access potentially extending beyond your Channel; neither WAHA, our app's Channel-ID check, nor reduced API permissions guarantee protection from account suspension. The tracker itself never reads private chats or sends to private chat/group IDs. Keep the server, session volume, QR code, API key and backups private. Never expose port 3000 publicly. The existing tracker UI/API does not implement authentication; don't expose it publicly without an authenticated reverse proxy or VPN. Linking your personal WhatsApp is your explicit choice; you can disconnect it from the phone at any time.

## 1. Prepare the existing deployment

Run these steps on the VM (Linux shell). This project now includes an optional `compose.yaml` for a combined deployment. **Do not overwrite your current `.env`, `data/hmt_tracker.db`, or existing Docker volume.** Do not run two tracker schedulers or more than one Uvicorn worker against the same DB. If you are using systemd, a different container name, a named data volume, or a reverse proxy, retain those settings and adapt the examples.

- Find the active database path and data mount first (for Docker, `docker inspect <existing-tracker-container>`; look at `Mounts` only, avoid sharing the output containing secrets).
- Back up the running DB consistently using SQLite's backup command, or stop the old tracker before copying the DB and any WAL/SHM files. For example, **after stopping your tracker**, `cp -a /path/to/existing/data /path/to/backup-data-2026-11-25`. Keep your existing `.env` separately and securely.
- Extract the updated source to a new directory or apply the provided patch on the original code. The source archive intentionally excludes the historical database backup from the uploaded source. Use the actual production data directory/volume, not an empty replacement.
- Copy `.env.example` to `.env` only for a fresh installation. For an existing deployment, append the WhatsApp configuration in step 5 to your current `.env` instead.
- Install Docker with Compose v2 if not already available (`docker compose version`). The combined deployment binds tracker port 8000 and WAHA port 3000 to loopback only. On Google Cloud do not open ingress for WAHA. Check free VM RAM and disk (`free -h`, `df -h`); WEBJS uses Chromium, and a small VM may need more memory.

For a bind-mounted database directory in a combined deployment, add this to `.env`, pointing to the existing directory:

```dotenv
TRACKER_DATA_DIR=/absolute/path/to/existing/data
DATABASE_PATH=data/hmt_tracker.db
```

For a named Docker volume, edit the `tracker.volumes` mapping in `compose.yaml` to use the existing named volume as `external: true` under `volumes`, mounted at `/app/data`. If `DATABASE_PATH` is different in your old deployment, preserve the path and mount accordingly. Stop the old tracker before starting the new one. You may start WAHA alone while the old tracker is running.

## 2. Create the Channel on your phone

WhatsApp → Updates → Channels → `+` → Create channel. Choose a name (e.g. HMT Watch Tracker), description and optional icon. For the first integration test you can use the final Channel, ideally before inviting followers. The invite URL is not the API Channel ID.

## 3. Start WAHA privately

In the updated project directory:

```bash
cp .env.waha.example .env.waha
chmod 600 .env.waha .env
openssl rand -hex 32
openssl rand -hex 32
```

Use the first random value as `WAHA_API_KEY` and the second as both dashboard and Swagger passwords (or generate separate passwords). Do not reuse your Telegram token, WhatsApp PIN, Google password, or the placeholders. Edit `.env.waha`:

```dotenv
WAHA_API_KEY=YOUR_GENERATED_API_KEY
WAHA_DASHBOARD_USERNAME=admin
WAHA_DASHBOARD_PASSWORD=YOUR_GENERATED_PASSWORD
WHATSAPP_SWAGGER_USERNAME=admin
WHATSAPP_SWAGGER_PASSWORD=YOUR_GENERATED_PASSWORD
WHATSAPP_DEFAULT_ENGINE=WEBJS
WAHA_EVENTS_DOWNLOAD_MEDIA=false
WAHA_API_DOWNLOAD_MEDIA=false
WAHA_LOG_LEVEL=warn
WAHA_HTTP_LOG_LEVEL=warn
TZ=Asia/Kolkata
WAHA_PRINT_QR=false
WAHA_WORKER_RESTART_SESSIONS=true
```

The supplied file uses WEBJS because WAHA documents both Channel sends and Channel history retrieval. It is not a guarantee of greater account safety. The incoming media download settings reduce unnecessary storage; they do not disable WhatsApp's linked-device sync or change outbound image sending. Optional extra security: set `WAHA_API_KEY=sha512:<SHA-512 hash of the generated key>` instead; use the original plain key for the dashboard and HTTP authentication. See [WAHA security](https://waha.devlike.pro/docs/how-to/security/).

```bash
docker compose pull waha
docker compose up -d waha
docker compose ps waha
```

The default image is `devlikeapro/waha:latest` (the free image, not a Plus subscription). Check WAHA's version in the dashboard; use at least 2026.6.1. For a reproducible deployment, pin `WAHA_IMAGE` in `.env` to the verified version/tag or image digest after testing. The Docker named volume `waha-sessions` persists authentication across container recreation; do not delete the volume (`docker compose down -v` would remove it). Treat the volume as equivalent to a logged-in WhatsApp device.

On your **local computer**, open an SSH tunnel to the VM (use your actual username and IP, or your usual Google Cloud SSH/IAP command with the same port forwarding):

```bash
ssh -N -L 3000:127.0.0.1:3000 YOUR_VM_USER@YOUR_VM_IP
```

Leave that terminal open. Open `http://127.0.0.1:3000/dashboard` in your local browser, enter the dashboard username/password, then connect using your WAHA API key. This does not require opening port 3000 in Google Cloud.

## 4. Link WhatsApp and obtain the real Channel ID

In the WAHA dashboard, start the `default` session. When it shows `SCAN_QR`, open its QR code. On your phone, WhatsApp → Linked devices → Link a device → scan QR. Wait for status `WORKING`. See the [WAHA quick start](https://waha.devlike.pro/docs/overview/quick-start/).

Open Swagger at `http://127.0.0.1:3000/` through the tunnel. Authenticate with the Swagger username/password, then click Authorize and enter the API key. Execute `GET /api/{session}/channels` with `session=default` and `role=OWNER`. Find your exact Channel name; copy its numeric ID ending in `@newsletter`. Or on the VM, using Bash (no literal API key in shell history):

```bash
read -rsp 'WAHA admin API key: ' WAHA_KEY; echo
curl -fsS -H "X-Api-Key: $WAHA_KEY" \
  'http://127.0.0.1:3000/api/default/channels?role=OWNER'
unset WAHA_KEY
```

The response includes `id`, `name`, `invite`, and `role`. Your `id` should resemble `123456789012345678@newsletter` (example only). Never use the invite URL or your personal phone number as `WHATSAPP_CHANNEL_ID`. Only numeric newsletter IDs are accepted by the tracker. If the list is empty, verify the session is WORKING, that the number owns the Channel, and refresh/retry once the Channel has synced. You can also use `GET /api/default/channels/{inviteCode}` with the invite URL's final segment.

**Recommended for your personal number:** after confirming the ID, create a session-scoped send-only key in the WAHA dashboard or Swagger `POST /api/keys` using the admin API key and the following body:

```json
{
  "isAdmin": false,
  "session": "default",
  "isActive": true,
  "actions": {
    "read": false,
    "send": true,
    "control": false,
    "setting": false,
    "app": false,
    "delete": false
  }
}
```

Copy the returned `key` for `WHATSAPP_API_KEY` in the tracker. Keep the WAHA admin key in `.env.waha` and off the tracker. This scopes API access but the `send` permission is not Channel-only; the tracker additionally enforces the configured newsletter ID. If your WAHA version lacks scoped keys, update it before proceeding or use the admin key for a local test only. The tracker never requires read or lifecycle API permissions.

## 5. Configure the tracker (keep automatic publishing off initially)

Append/update these keys in the **existing** `.env`. Leave all Telegram and scraper settings as they are:

```dotenv
WHATSAPP_ENABLED=false
WHATSAPP_API_URL=http://waha:3000
WHATSAPP_API_KEY=YOUR_WAHA_SEND_KEY
WHATSAPP_SESSION=default
WHATSAPP_CHANNEL_ID=YOUR_NUMERIC_ID@newsletter
WHATSAPP_TIMEOUT_SECONDS=45
WHATSAPP_MIN_INTERVAL_SECONDS=3
WHATSAPP_MAX_ATTEMPTS=8
WHATSAPP_MAX_AGE_SECONDS=3600
```

Use `http://waha:3000` when tracker and WAHA share the Compose network `hmt-notifications`. If running Python directly on the VM, use `http://127.0.0.1:3000` instead. If retaining your own Docker run or separate Compose deployment, connect the tracker container to the `hmt-notifications` network persistently and use `http://waha:3000`; e.g. use `--network hmt-notifications` when recreating it, or declare an external network in its compose file. `localhost` inside a tracker container is not WAHA. Do not change your existing data mount. Restart/recreate the tracker after changing environment variables, since config is loaded on process start.

## 6. Test text and images before automatic posting

These commands send **real, clearly labelled test updates** to the configured Channel, even with `WHATSAPP_ENABLED=false`. No existing alert is modified. The CLI deliberately avoids adding an unauthenticated HTTP endpoint for posting or retrying.

For Compose, after the database path/mount is verified and the old tracker is stopped (so only one process performs the migration), build the new image:

```bash
docker compose build tracker
docker compose run --rm --no-deps tracker python whatsapp_cli.py status
docker compose run --rm --no-deps tracker python whatsapp_cli.py test-text
docker compose run --rm --no-deps tracker python whatsapp_cli.py test-image --url 'https://github.com/devlikeapro/waha/raw/core/examples/dev.likeapro.jpg'
```

Or test with a real catalogue watch image: `docker compose run --rm --no-deps tracker python whatsapp_cli.py test-image --watch-id YOUR_EXISTING_WATCH_ID`. You can also use the direct product-image URL from either HMT website with `--url`. Test at least one image from each source; the initial test URL is WAHA's documented example, not an HMT image.

Check the Channel on your phone after **each** command. A WAHA response with a message ID is treated as acceptance; it is not proof that the message reached the Channel or every follower. If nothing appears, do not repeatedly resend: verify the session, Channel role/ID, engine and API permissions, inspect WAHA logs privately and try once after diagnosing. HMT image URLs may occasionally fail to fetch or be expired. No automatic text fallback is attempted after an ambiguous media-send response, to avoid duplicate posts. If there is no image URL in the snapshot or current catalogue, the worker sends text instead.

## 7. Enable both notification services

After both test posts appear, change `.env`:

```dotenv
WHATSAPP_ENABLED=true
```

With the old tracker stopped and the correct production DB mount confirmed, start the updated tracker:

```bash
docker compose up -d --build tracker
docker compose logs -f tracker
```

For non-Compose deployments, rebuild/restart the existing application using its normal deployment mechanism and the new environment variables. For host Python, ensure the environment is loaded before starting Uvicorn, e.g. `uvicorn app:app --env-file .env --host 127.0.0.1 --port 8000` (or keep your existing secured listen address). For host CLI use `set -a; . ./.env; set +a` in Bash if your `.env` is shell-compatible, then `python whatsapp_cli.py test-text` etc. Do not expose the tracker UI publicly without authentication, because existing endpoints allow changing rules, deleting alerts, and manually running scrapes.

The combined Compose file binds tracker HTTP to loopback. Use your existing authenticated reverse proxy or another SSH tunnel `ssh -N -L 8000:127.0.0.1:8000 YOUR_VM_USER@YOUR_VM_IP` and open `http://localhost:8000`. Existing Telegram test/retry controls continue to apply to Telegram only. Settings shows WAHA configuration and counts; Alerts shows both delivery states, WhatsApp timestamps and errors. `GET /api/config` and `/api/alerts` expose non-secret delivery fields only (channel/session identifiers are visible in alert history; API keys are not).

**Avoid repeated live posts just to test.** After enabling, use an ordinary newly detected stock event or a tracked watch rule that you intentionally want to announce. An existing alert is not automatically replayed to WhatsApp.

## 8. Delivery semantics and troubleshooting

- The existing `alerts.status`, `attempts`, Telegram timestamps and retry endpoints remain Telegram-only. WhatsApp adds `whatsapp_*` columns in the same record. The schema migration adds columns/indexes automatically and preserves old rows.
- Alerts created before enabling, while disabled or with invalid configuration are `skipped`; no historic alert flood. New events have independent delivery state and a stored session/Channel ID. Changing the target will not redirect queued old-target alerts. The original repeat-alert timer still depends on successful Telegram delivery, as before.
- `pending` / `retrying`: queued for processing; `sending`: in progress; `sent`: WAHA returned a successful message ID (shown as Accepted in Alerts); `failed`: terminal rejection or retry limit; `uncertain`: delivery could have occurred, review manually; `expired`: too old to publish; `skipped`: no WhatsApp target at alert creation.
- Explicit 401/403/404/422/429 responses and connection failures known to occur before send use bounded retries with exponential delay, and 429 honors the numeric Retry-After (minimum 60s). A 5xx, read timeout, connection interruption, missing message ID, or crashed in-flight send is uncertain instead of blindly retried. There is no end-to-end exactly-once guarantee. A lost DB write or successful response with no visible Channel post also needs manual review.
- Alerts older than one hour are not automatically posted; change `WHATSAPP_MAX_AGE_SECONDS` if you prefer a different limit. An event snapshot's status/price/detection time is preserved, rather than rewriting an older event to reflect current catalogue stock. Even an alert less than an hour old may no longer reflect current stock; followers should check the purchase link.
- Deleting an alert removes its outstanding queued deliveries; a request already in flight cannot be recalled. No replay of old skipped or expired entries is implemented. A paused same-target queue can resume only within the configured age limit.

Inspect status and retry after verifying the Channel has **not** received the alert (replace `123` with the actual alert ID from the UI/API):

```bash
docker compose exec tracker python whatsapp_cli.py status
docker compose exec tracker python whatsapp_cli.py retry 123 --confirm-not-posted
```

The manual retry only supports `failed`/`uncertain` for the current target and remains subject to the age limit. The original Telegram retry button will not trigger WhatsApp. If a session has disconnected, fix it via the WAHA dashboard before retrying. A WAHA error alone does not mean the Channel post failed.

## 9. Stop safely or roll back

To stop future WhatsApp automatic posts, set `WHATSAPP_ENABLED=false` and recreate/restart only the tracker. To disconnect your number, open WhatsApp → Linked devices → select the WAHA linked device → Log out, then stop WAHA (`docker compose stop waha`). If you intend to remove the session data, delete the WAHA session through its dashboard or remove only the WAHA volume after logout, never your SQLite volume. Telegram remains independent. The previous code can ignore the added SQLite columns, but keep the DB backup and do not restore an old copy over newer catalogue data unless necessary. If you restore original code, preserve all original deployment flags and data mounts.

## 10. Validation / limitations

The original 60 tests pass, plus new tests for schema migration, independent delivery, photo formatting, text fallback, rate-limit retries, uncertain results, target checks, age expiry, crash recovery and deletion. These use mocked WAHA responses and temporary SQLite files. No real WhatsApp credentials, phone or live Channel were available here. Docker/WAHA live deployment was not performed; your VM's resources and real HMT image publication must be tested using the above steps.

References: [WAHA free release](https://waha.devlike.pro/blog/waha-2026-6/), [Channels](https://waha.devlike.pro/docs/how-to/channels/), [installation](https://waha.devlike.pro/docs/how-to/install/), [security and API keys](https://waha.devlike.pro/docs/how-to/security/), [configuration](https://waha.devlike.pro/docs/how-to/config/), [send media](https://waha.devlike.pro/docs/how-to/send-messages/).
