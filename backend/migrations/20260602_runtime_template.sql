-- Runtime template migration for existing PostgreSQL databases.
-- New test/dev databases created through Base.metadata.create_all do not need this file.

CREATE TABLE IF NOT EXISTS workflow_run (
    id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES workflow(id) ON DELETE CASCADE,
    execution_attempt INTEGER NOT NULL DEFAULT 1,
    thread_id VARCHAR(160) NOT NULL UNIQUE,
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    entrypoint VARCHAR(64) NOT NULL DEFAULT 'information_collection',
    error_message TEXT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS workflow_pause (
    id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES workflow(id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES workflow_run(id) ON DELETE CASCADE,
    node_name VARCHAR(64) NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    options JSON NOT NULL DEFAULT '[]'::json,
    context JSON NOT NULL DEFAULT '{}'::json,
    suggested_route VARCHAR(64) NULL,
    is_resolved BOOLEAN NOT NULL DEFAULT false,
    decision JSON NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ NULL
);

ALTER TABLE workflow
    ADD COLUMN IF NOT EXISTS current_run_id UUID NULL;

ALTER TABLE workflow_event
    ADD COLUMN IF NOT EXISTS run_id UUID NULL REFERENCES workflow_run(id) ON DELETE CASCADE;

ALTER TABLE workflow_node_state
    ADD COLUMN IF NOT EXISTS run_id UUID NULL REFERENCES workflow_run(id) ON DELETE CASCADE;

ALTER TABLE artifact
    ADD COLUMN IF NOT EXISTS run_id UUID NULL REFERENCES workflow_run(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS ix_workflow_run_workflow_id ON workflow_run(workflow_id);
CREATE INDEX IF NOT EXISTS ix_workflow_run_status ON workflow_run(status);
CREATE INDEX IF NOT EXISTS ix_workflow_pause_run_id ON workflow_pause(run_id);
CREATE INDEX IF NOT EXISTS ix_workflow_pause_active ON workflow_pause(workflow_id, run_id, is_resolved);
CREATE INDEX IF NOT EXISTS ix_workflow_event_run_id ON workflow_event(run_id);
CREATE INDEX IF NOT EXISTS ix_workflow_node_state_run_id ON workflow_node_state(run_id);
CREATE INDEX IF NOT EXISTS ix_artifact_run_id ON artifact(run_id);
