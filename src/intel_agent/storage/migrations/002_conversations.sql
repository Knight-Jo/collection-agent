CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'intake',
    brief TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    task_id TEXT,
    citations TEXT,
    sequence INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE timeline (
    timeline_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    task_id TEXT,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    detail TEXT,
    at TEXT NOT NULL,
    sequence INTEGER NOT NULL
);
