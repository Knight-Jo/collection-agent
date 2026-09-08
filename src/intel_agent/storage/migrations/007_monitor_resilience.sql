-- Monitor scheduling resilience (spec 002 US2): failure-backoff state and
-- change-report deduplication so a stale baseline cannot flood repeats.

ALTER TABLE monitors ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0;

CREATE TABLE monitor_reported_changes (
    monitor_id TEXT NOT NULL REFERENCES monitors(monitor_id),
    fingerprint TEXT NOT NULL,
    first_run_id TEXT,
    last_run_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (monitor_id, fingerprint)
);
