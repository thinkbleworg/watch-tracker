from dataclasses import replace
from unittest.mock import Mock
from config import config
from database import Database
from priority_scheduler import PriorityScheduler, PriorityTracker
from tracker import Tracker, TrackerRunResult
from tests.test_tracker import make_watch, make_matching_rule


def test_workers_have_distinct_execution_locks_and_source_configs(tmp_path):
    db = Database(tmp_path/'test.db')
    scheduler = PriorityScheduler(Tracker(db), database=db)
    a,b = scheduler.workers.values()
    assert a._execution_lock is not b._execution_lock
    assert len(a.tracker.config.sources) == len(b.tracker.config.sources) == 1
    assert a.tracker.config.sources != b.tracker.config.sources
    a._execution_lock.acquire()
    try:
        b.tracker.run = Mock(return_value=TrackerRunResult(run_id=1, success=True))
        assert b.run_now().success
    finally:
        a._execution_lock.release()


def test_priority_without_rules_skips_source(tmp_path):
    tracker = PriorityTracker(Database(tmp_path/'test.db'))
    tracker.mode = 'priority'
    tracker._scrape_source = Mock()
    result = tracker._run_source('hmt.store', rules=[], seed_only=False, alert_callback=None)
    assert result.success
    tracker._scrape_source.assert_not_called()


def test_discovery_then_priority_and_failed_discovery_retries(tmp_path, monkeypatch):
    tracker = PriorityTracker(Database(tmp_path/'test.db'))
    monkeypatch.setattr(Tracker, 'run', lambda *a, **k: TrackerRunResult(run_id=1, success=True))
    tracker.run()
    assert tracker.mode == 'discovery'
    tracker.run()
    assert tracker.mode == 'priority'
    tracker.discovery_due = 0
    monkeypatch.setattr(Tracker, 'run', lambda *a, **k: TrackerRunResult(run_id=1, success=False))
    tracker.run()
    assert tracker.discovery_due == 0


def test_priority_persists_only_matching_watches(tmp_path):
    db = Database(tmp_path/'test.db')
    tracker = PriorityTracker(db)
    tracker.mode = 'priority'
    watch = make_watch();watch.name = 'Unrelated'; watch.model_number = None; watch.sku = None
    from tracker import SourceRunResult
    tracker._process_watch(watch, is_new=True, rules=[make_matching_rule()], seed_only=False,
                           result=SourceRunResult(source=watch.source), alert_callback=None)
    assert db.count_watches() == 0


def test_status_exposes_each_source_and_cooldowns(tmp_path):
    db = Database(tmp_path/'test.db')
    scheduler = PriorityScheduler(Tracker(db), database=db)
    status = scheduler.status()
    assert set(status['sources']) == {'hmt.in', 'hmt.store'}
    assert 'http_hosts' in status
