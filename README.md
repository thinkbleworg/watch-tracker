# HMT Watch Tracker

A Python-based HMT watch availability tracker that monitors:

- https://hmtwatches.in
- https://www.hmtwatches.store

The tracker maintains a persistent catalogue, checks stock periodically,
and can send Telegram notifications for newly discovered watches.

---

## Features

### Two HMT sources

The tracker supports both HMT stores through separate scrapers:

- `hmt.in`
  - HMT's official website
  - HTML-based product discovery
  - `/filter_products`
  - `/all_product`
  - product-page verification support

- `hmt.store`
  - SmartPOS-backed catalogue
  - direct SmartPOS REST API
  - paginated product discovery
  - stock quantity support

---

## Alert behaviour

The important distinction is between the catalogue and alerts.

The catalogue contains all watches discovered by the tracker.

Telegram alerts are much more selective.

### First run

The first successful catalogue build is silent.

The tracker discovers and stores watches but does not send a Telegram
notification for every existing watch.

This prevents an initial flood of messages.

### Later runs

A Telegram alert can be generated when:

1. a watch is newly discovered,
2. the watch is currently in stock,
3. the watch matches at least one enabled tracking rule.

A watch that remains in stock on later runs does not generate another
notification unless repeated alerts are enabled in Settings.

By default the following are disabled:

- back-in-stock alerts
- repeated in-stock alerts
- out-of-stock alerts
- price-change alerts

Repeated in-stock alerts can be enabled from the Settings page and the
interval can be changed without editing environment variables.

---

## Stock information

When a reliable quantity is available, the notification and UI show
the quantity.

For example:

    10 available

If the source only confirms availability without a reliable quantity:

    In stock

The tracker does not invent a stock quantity.

---

## Tracking

Tracking rules determine which watches can generate alerts.

Rules can be configured using:

- source
- include keywords
- exclude keywords
- explicit product IDs
- minimum stock

For example:

    Include: sona
    Source: hmt.store
    Minimum stock: 1

A rule can also exclude unwanted watches.

Example:

    Include: janata
    Exclude: quartz

The catalogue is still populated with all discovered watches regardless
of whether they match an alert rule.

---

## Project structure

    hmt-watch-tracker/
    │
    ├── app.py
    ├── config.py
    ├── models.py
    ├── database.py
    ├── tracker.py
    ├── notifier.py
    ├── scheduler.py
    │
    ├── scrapers/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── hmt_official.py
    │   └── hmt_store.py
    │
    ├── templates/
    │   ├── base.html
    │   └── dashboard.html
    │
    ├── static/
    │   ├── style.css
    │   └── app.js
    │
    ├── tests/
    │   ├── __init__.py
    │   ├── test_models.py
    │   ├── test_tracker.py
    │   └── test_scrapers.py
    │
    ├── data/
    │   └── .gitkeep
    │
    ├── requirements.txt
    ├── .env.example
    └── README.md

---

## Installation

Create a virtual environment.

### Linux / macOS

    python3 -m venv .venv
    source .venv/bin/activate

### Windows

    python -m venv .venv
    .venv\Scripts\activate

Install dependencies:

    pip install -r requirements.txt

---

## Configuration

Copy:

    .env.example

to:

    .env

Then configure Telegram:

    TELEGRAM_BOT_TOKEN=your_bot_token
    TELEGRAM_CHAT_ID=your_chat_id

The application can run without Telegram credentials for scraping and
catalogue testing. Telegram delivery simply will not be available.

---

## Running locally

Start FastAPI with Uvicorn:

    uvicorn app:app --host 0.0.0.0 --port 8000

Then open:

    http://localhost:8000

The application starts the scheduler and performs the configured startup
run.

---

## Scheduler

The default interval is:

    300 seconds

which is five minutes.

The scheduler:

1. starts,
2. runs the tracker,
3. waits five minutes,
4. runs again.

The tracker has an internal lock so overlapping runs are prevented.

---

## Manual run

The dashboard provides a `Run Now` button.

This starts an immediate tracker run without waiting for the next
scheduled interval.

---

## Database

SQLite is used for persistence.

The default database is:

    data/hmt_tracker.db

The database stores:

- watches
- tracking rules
- alert states
- alert history
- scrape runs
- source status

The catalogue and alert history are intentionally separate.

---

## Source failure handling

A failed source must not be interpreted as "everything is out of stock."

If a source fails:

- its previous catalogue state is preserved,
- no false out-of-stock transition is generated,
- the failed source is recorded in scrape/source status,
- the other source can continue processing.

This is particularly important for a five-minute polling system.

---

## HMT Store API

The `.store` scraper uses the SmartPOS catalogue API rather than browser
automation.

The relevant API endpoint is:

    https://smartpos.amazon.in/api-unauthenticated/resources/external/catalog/products

The HMT shop ID is:

    48236

The request is paginated using:

    offset
    limit

and requests grouped variants.

Stock determination primarily uses:

    buyingOptions.singlePurchase.availability.isBuyable

and:

    currentStock

The scraper also respects:

    additionalAttributes.isOOS

---

## HMT Official website

The official HMT source uses the site's product filtering endpoint and
HTML catalogue responses.

The scraper normalizes the source data into the common `Watch` model.

The project deliberately keeps the two source implementations separate
because the two websites expose product and stock information differently.

---

## Testing

Run:

    pytest

The tests cover:

- Watch model behaviour
- tracking rules
- database basics
- SmartPOS stock parsing
- product response parsing

Tests do not depend on live HMT websites.

Live source checks should be performed separately during development.

---

## Deployment

For production, the application can run as a continuously running
FastAPI service.

A typical production architecture is:

    FastAPI
        |
        +-- tracker
        |
        +-- scheduler
        |
        +-- SQLite / persistent storage
        |
        +-- Telegram

For cloud deployment, use a persistent database/storage strategy rather
than relying on an ephemeral container filesystem.

If multiple application instances are deployed, do not allow every
instance to run its own five-minute scheduler. Use a single scheduler
instance or an external scheduler such as Cloud Scheduler.

---

## Important operational rule

Do not change the meaning of a source failure into an out-of-stock state.

A scraper returning zero watches because the website failed is not the
same thing as the website returning zero watches.

This distinction prevents false Telegram notifications.

---

## Development order

The core implementation is organized into:

1. `models.py`
2. `database.py`
3. `scrapers/base.py`
4. `scrapers/hmt_official.py`
5. `scrapers/hmt_store.py`
6. `tracker.py`
7. `notifier.py`
8. `scheduler.py`
9. `app.py`
10. templates/static files
11. tests

---

## Current alert policy

The default policy is intentionally conservative:

    First run:
        catalogue only
        no Telegram flood

    New watch:
        alert if in stock and tracked

    Existing watch still in stock:
        no alert

    Existing watch becomes back in stock:
        no alert by default

    Price changes:
        no alert by default

    Out of stock:
        no alert by default

This can be expanded later without changing the basic catalogue model.