-- Monitor watch-source gates: cheap change-detection state (spec 002 US2).
-- Per watched page: conditional-request validators and content hashes so a
-- monitor run can skip the research loop when nothing changed.

CREATE TABLE monitor_watch_sources (
    monitor_id TEXT NOT NULL REFERENCES monitors(monitor_id),
    url TEXT NOT NULL,
    etag TEXT,
    last_modified TEXT,
    byte_hash TEXT,
    content_hash TEXT,
    last_checked_at TEXT,
    last_outcome TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (monitor_id, url)
);

ALTER TABLE monitor_runs ADD COLUMN gate_outcome TEXT NOT NULL DEFAULT '';
