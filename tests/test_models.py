from models import TrackingRule, Watch


def make_watch(
    *,
    in_stock=True,
    stock_count=5,
):
    return Watch.create(
        id="test-watch-1",
        source="hmt.store",
        name="HMT Janata Automatic",
        model_number="Janata",
        sku="SKU123",
        price=5000,
        mrp=5500,
        product_url="https://example.com/watch",
        image_url=None,
        in_stock=in_stock,
        stock_count=stock_count,
        category=None,
        collection="Janata Automatic",
        gender="Men",
    )


def test_watch_create_sets_timestamps():
    watch = make_watch()

    assert watch.first_seen
    assert watch.last_seen
    assert watch.last_stock_check


def test_watch_display_stock():
    watch = make_watch(
        in_stock=True,
        stock_count=5,
    )

    assert watch.display_stock == "5 available"


def test_watch_display_stock_without_quantity():
    watch = make_watch(
        in_stock=True,
        stock_count=None,
    )

    assert watch.display_stock == "In stock"


def test_watch_display_oos():
    watch = make_watch(
        in_stock=False,
        stock_count=0,
    )

    assert watch.display_stock == "Out of stock"


def test_tracking_rule_matches_keyword():
    watch = make_watch()

    rule = TrackingRule(
        id="rule-1",
        name="Janata watches",
        include_keywords=["janata"],
    )

    assert rule.matches(watch)


def test_tracking_rule_excludes_keyword():
    watch = make_watch()

    rule = TrackingRule(
        id="rule-1",
        name="Exclude Janata",
        exclude_keywords=["janata"],
    )

    assert not rule.matches(watch)


def test_tracking_rule_source_filter():
    watch = make_watch()

    rule = TrackingRule(
        id="rule-1",
        name="Official only",
        source="hmt.in",
    )

    assert not rule.matches(watch)


def test_tracking_rule_minimum_stock():
    watch = make_watch(
        in_stock=True,
        stock_count=2,
    )

    rule = TrackingRule(
        id="rule-1",
        name="Minimum three",
        minimum_stock=3,
    )

    assert not rule.matches(watch)


def test_tracking_rule_product_id():
    watch = make_watch()

    rule = TrackingRule(
        id="rule-1",
        name="Exact watch",
        product_ids=["test-watch-1"],
    )

    assert rule.matches(watch)