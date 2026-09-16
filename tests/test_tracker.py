from dataclasses import replace

from config import config
from database import Database
from models import TrackingRule, Watch
from tracker import SourceRunResult, Tracker


def make_tracker_config():
    return replace(
        config,
        alert_back_in_stock=True,
        alert_only_when_in_stock=True,
        alert_new_products_only=True,
    )


def make_watch(
    watch_id="watch-1",
    in_stock=True,
):
    return Watch.create(
        id=watch_id,
        source="hmt.store",
        name="HMT Test Watch",
        model_number="TEST",
        sku="TEST-SKU",
        price=1000,
        mrp=1200,
        product_url="https://example.com/watch",
        image_url=None,
        in_stock=in_stock,
        stock_count=5 if in_stock else 0,
        category=None,
        collection="Test",
        gender="Men",
    )


def make_matching_rule():
    return TrackingRule(
        id="rule-1",
        name="Test Rule",
        include_keywords=["test"],
    )


def process_existing_watch(
    db,
    tracker,
    watch,
    *,
    result=None,
    rules=None,
):
    if result is None:
        result = SourceRunResult(source=watch.source)

    if rules is None:
        rules = [make_matching_rule()]

    tracker._process_watch(
        watch,
        is_new=False,
        rules=rules,
        seed_only=False,
        result=result,
        alert_callback=None,
    )

    return result


def test_new_watch_is_stored(tmp_path):
    db = Database(str(tmp_path / "test.db"))

    watch = make_watch()

    db.save_watch(watch)

    stored = db.get_watch("watch-1")

    assert stored is not None
    assert stored.name == "HMT Test Watch"


def test_database_starts_empty(tmp_path):
    db = Database(str(tmp_path / "test.db"))

    assert db.count_watches() == 0


def test_tracking_rule_can_be_saved(tmp_path):
    db = Database(str(tmp_path / "test.db"))

    rule = TrackingRule(
        id="rule-1",
        name="Test Rule",
        include_keywords=["test"],
    )

    db.save_tracking_rule(rule)

    rules = db.get_tracking_rules()

    assert len(rules) == 1
    assert rules[0].name == "Test Rule"


def test_out_of_stock_to_in_stock_creates_back_in_stock_alert(tmp_path):
    db = Database(str(tmp_path / "test.db"))

    tracker = Tracker(
        db,
        tracker_config=make_tracker_config(),
    )

    db.save_watch(
        make_watch(
            watch_id="watch-1",
            in_stock=False,
        )
    )

    new_watch = make_watch(
        watch_id="watch-1",
        in_stock=True,
    )

    result = process_existing_watch(
        db,
        tracker,
        new_watch,
    )

    alerts = db.get_alerts()

    assert result.alerts_created == 1
    assert len(alerts) == 1

    assert alerts[0]["watch_id"] == "watch-1"
    assert alerts[0]["alert_type"] == "back_in_stock"
    assert alerts[0]["status"] == "pending"

    stored = db.get_watch("watch-1")

    assert stored is not None
    assert stored.in_stock is True
    assert stored.stock_count == 5


def test_in_stock_to_in_stock_does_not_create_duplicate_alert(tmp_path):
    db = Database(str(tmp_path / "test.db"))

    tracker = Tracker(
        db,
        tracker_config=make_tracker_config(),
    )

    db.save_watch(
        make_watch(
            watch_id="watch-1",
            in_stock=True,
        )
    )

    new_watch = make_watch(
        watch_id="watch-1",
        in_stock=True,
    )

    result = process_existing_watch(
        db,
        tracker,
        new_watch,
    )

    alerts = db.get_alerts()

    assert result.alerts_created == 0
    assert len(alerts) == 0


def test_watch_can_alert_again_after_going_out_of_stock_and_returning(
    tmp_path,
):
    db = Database(str(tmp_path / "test.db"))

    tracker = Tracker(
        db,
        tracker_config=make_tracker_config(),
    )

    db.save_watch(
        make_watch(
            watch_id="watch-1",
            in_stock=False,
        )
    )

    first_in_stock = make_watch(
        watch_id="watch-1",
        in_stock=True,
    )

    first_result = process_existing_watch(
        db,
        tracker,
        first_in_stock,
    )

    assert first_result.alerts_created == 1

    out_of_stock = make_watch(
        watch_id="watch-1",
        in_stock=False,
    )

    second_result = process_existing_watch(
        db,
        tracker,
        out_of_stock,
    )

    assert second_result.alerts_created == 0

    second_in_stock = make_watch(
        watch_id="watch-1",
        in_stock=True,
    )

    third_result = process_existing_watch(
        db,
        tracker,
        second_in_stock,
    )

    alerts = db.get_alerts()

    assert third_result.alerts_created == 1
    assert len(alerts) == 2

    assert all(
        alert["watch_id"] == "watch-1"
        for alert in alerts
    )

    assert all(
        alert["alert_type"] == "back_in_stock"
        for alert in alerts
    )