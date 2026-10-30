"""Independent source workers sharing host pacing and the durable alert outbox."""
from dataclasses import replace
import time
from scheduler import TrackerScheduler
from tracker import Tracker
from scrapers.http_policy import policy_status


class PriorityTracker(Tracker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.discovery_due = 0.0
        self.mode = 'discovery'

    def run(self, **kwargs):
        discovery = time.monotonic() >= self.discovery_due
        self.mode = 'discovery' if discovery else 'priority'
        result = super().run(**kwargs)
        if discovery and result.success:
            self.discovery_due = time.monotonic() + 900
        return result

    def _run_source(self, source, **kwargs):
        from tracker import SourceRunResult
        if self.mode == 'priority' and not any(r.source in (None, source) for r in kwargs['rules']):
            return SourceRunResult(source=source, success=True)
        result = super()._run_source(source, **kwargs)
        if self.mode == "priority":
            result.new_products = 0
        return result

    def _scrape_source(self, source, on_watch=None):
        # Bulk endpoints amortize request cost across all tracked watches.
        # Discovery retains every product; priority commits only tracked products.
        rules = self.db.get_tracking_rules(enabled_only=True)
        if self.mode == 'priority' and not any(r.source in (None, source) for r in rules):
            return []
        def selected(watch):
            return self.mode == 'discovery' or any(replace(rule, minimum_stock=0).matches(watch) for rule in rules)
        def stream(watch):
            if on_watch and selected(watch):
                on_watch(watch)
        watches = super()._scrape_source(source, on_watch=stream)
        # Return the observed catalogue to preserve run health/count semantics;
        # _process_watch below restricts commits during priority cycles.
        return watches

    def _process_watch(self, watch, **kwargs):
        if self.mode == 'priority' and not any(replace(r, minimum_stock=0).matches(watch) for r in kwargs['rules']):
            return
        return super()._process_watch(watch, **kwargs)


class PriorityScheduler:
    def __init__(self, tracker, *, interval_seconds=None, database=None, alert_callback=None):
        self.workers = {}
        for source in tracker.config.sources:
            if source.enabled:
                engine = PriorityTracker(database, tracker_config=replace(tracker.config, sources=(source,)))
                self.workers[source.name] = TrackerScheduler(engine,
                    interval_seconds=interval_seconds, database=database, alert_callback=alert_callback)

    def start(self, *, run_immediately=False):
        for worker in self.workers.values():
            worker.start(run_immediately=run_immediately)

    def stop(self, timeout=10):
        for worker in self.workers.values():
            worker.stop(timeout=timeout)

    @property
    def running(self):
        return bool(self.workers) and all(w.running for w in self.workers.values())

    def run_now(self):
        # Manual execution uses the same locks as scheduled source executions.
        from concurrent.futures import ThreadPoolExecutor
        from tracker import TrackerRunResult
        if any(w.execution_running for w in self.workers.values()):
            raise RuntimeError('A source check is already running.')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda w: w.run_now(), self.workers.values()))
        if not results:
            raise RuntimeError('No enabled sources.')
        return TrackerRunResult(run_id=results[0].run_id, success=any(r.success for r in results),
            sources=[s for r in results for s in r.sources],
            total_products=sum(r.total_products for r in results),
            new_products=sum(r.new_products for r in results),
            in_stock_products=sum(r.in_stock_products for r in results),
            alerts_created=sum(r.alerts_created for r in results))

    def status(self):
        states = {name: {**w.status(), 'mode': w.tracker.mode,
                   'discovery_due_in_seconds': max(0, round(w.tracker.discovery_due-time.monotonic()))}
                  for name, w in self.workers.items()}
        runs = [w.last_result for w in self.workers.values() if w.last_result]
        times = [w.last_run_at for w in self.workers.values() if w.last_run_at]
        return {'running': self.running, 'execution_running': any(w.execution_running for w in self.workers.values()),
                'interval_seconds': min((s['interval_seconds'] for s in states.values()), default=60),
                'night_mode': any(s['night_mode'] for s in states.values()),
                'last_run_at': max(times, default=None),
                'last_error': '; '.join(s['last_error'] for s in states.values() if s['last_error']) or None,
                'last_result': TrackerScheduler._result_to_dict(runs[-1]) if runs else None,
                'sources': states, 'http_hosts': policy_status()}
