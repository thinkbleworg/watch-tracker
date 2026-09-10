from database import Database
from models import TrackingRule, Watch
from tracker import Tracker


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