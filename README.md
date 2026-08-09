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

- Official-site product IDs are derived from a stable slug of the
  product name (`scrapers/hmt_official.py`), not from the site's
  product URL -- that URL is Laravel-encrypted and changes on every
  request, so it can't be used as an identity key.
- If you rename this repo or move hosts, `snapshots/snapshot.json`
  is the only state that matters -- copy it over so history
  (first_seen/last_seen) and "is this actually new" detection carry
  through.
- GitHub Actions' `schedule` trigger is best-effort and unreliable
  below ~10-15 minutes. For a true 5-minute cadence, run this from a
  cron job on a small VPS/free-tier VM instead (see chat / project
  notes for options).
