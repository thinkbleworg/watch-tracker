
from types import SimpleNamespace

from database import Database
from models import Watch
from notifier import TelegramNotifier


class FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload or {
            "ok": True,
            "result": {"message_id": 123},
        }

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, *, data, timeout):
        self.calls.append(
            {
                "url": url,
                "data": data,
                "timeout": timeout,
            }
        )
        return FakeResponse()


def make_watch():
    return Watch.create(
        id="watch-image-1",
        source="hmt.store",
        name="HMT Men Gandaberunda",
        product_url="https://example.com/gandaberunda",
        image_url="https://example.com/gandaberunda.jpg",
        in_stock=True,
        stock_count=5,
        price=8500,
    )


def test_watch_alert_sends_image_before_details(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    notifier = TelegramNotifier(
        db,
        bot_token="token",
        chat_id="chat",
    )

    session = FakeSession()
    notifier._session = session

    result = notifier._send_watch_message(
        make_watch(),
        alert_type="tracked",
    )

    assert result["ok"] is True
    assert len(session.calls) == 1

    call = session.calls[0]

    assert call["url"].endswith("/sendPhoto")
    assert call["data"]["chat_id"] == "chat"
    assert call["data"]["photo"] == "https://example.com/gandaberunda.jpg"
    assert "<b>HMT Men Gandaberunda</b>" in call["data"]["caption"]
    assert "Source:" in call["data"]["caption"]
    assert "Price:" in call["data"]["caption"]
    assert "Stock:" in call["data"]["caption"]


def test_watch_without_image_falls_back_to_text(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    notifier = TelegramNotifier(
        db,
        bot_token="token",
        chat_id="chat",
    )

    session = FakeSession()
    notifier._session = session

    watch = make_watch()
    watch.image_url = None

    notifier._send_watch_message(
        watch,
        alert_type="repeat",
    )

    assert len(session.calls) == 1
    assert session.calls[0]["url"].endswith("/sendMessage")
    assert "<b>HMT Men Gandaberunda</b>" in session.calls[0]["data"]["text"]


def test_retry_uses_current_watch_image(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    watch = make_watch()
    db.save_watch(watch)

    db.create_alert(
        watch=watch,
        alert_type="repeat",
        status="pending",
    )

    notifier = TelegramNotifier(
        db,
        bot_token="token",
        chat_id="chat",
    )

    session = FakeSession()
    notifier._session = session

    result = notifier.retry_pending_alerts()

    assert result == {
        "attempted": 1,
        "sent": 1,
        "failed": 0,
    }

    assert len(session.calls) == 1
    assert session.calls[0]["url"].endswith("/sendPhoto")
    assert session.calls[0]["data"]["photo"] == watch.image_url
