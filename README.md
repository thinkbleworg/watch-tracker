# HMT Watch Tracker

Scrapes hmtwatches.in and hmtwatches.store, diffs against the last
snapshot, and sends Telegram alerts for new / sold out / back in
stock / price-changed watches.

## Setup

```bash
pip install -r requirements.txt
export BOT_TOKEN="your-telegram-bot-token"
export CHAT_ID="your-telegram-chat-id"
python main.py
```

`BOT_TOKEN` / `CHAT_ID` must be set as environment variables --
`config.py` will refuse to start without them. Never commit real
values; in GitHub Actions they come from repo Secrets (see
`.github/workflows/monitor.yml`).

## Notes

- Tracker only cares about **Available** watches. Out-of-stock
  listings are scraped (needed to know a card exists at all) but
  discarded immediately and never persisted or compared -- the only
  alert sent is "a watch is available now that wasn't in the last
  check" (covers a genuinely new product or a previous one coming
  back in stock).
- Official-site product IDs are derived from a stable slug of the
  product name (`scrapers/hmt_official.py`), not from the site's
  product URL -- that URL is Laravel-encrypted and changes on every
  request, so it can't be used as an identity key.
- All timestamps (`first_seen`/`last_seen`/`last_available`) are
  stored and displayed in IST regardless of the server's system
  timezone -- see `timeutils.py`.
- Hosted on an Oracle Cloud Always Free VM via a systemd timer
  running every 5 minutes -- see `deploy/oracle-cloud/`. GitHub
  Actions' `schedule` trigger has been intentionally removed from
  `.github/workflows/monitor.yml` (kept as manual `workflow_dispatch`
  only) to avoid duplicate alerts and two diverging snapshot copies.
- If you rename this repo or move hosts, `snapshots/snapshot.json`
  is the only state that matters -- copy it over so "is this
  actually new" detection carries through.
