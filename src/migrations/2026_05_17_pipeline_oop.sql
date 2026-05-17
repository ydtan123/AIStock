-- 2026-05-17: OOP pipeline column additions for selected_stocks.
-- Idempotency is provided by the MigrationRunner (skips if version present).
-- These statements are written for MySQL.

ALTER TABLE selected_stocks
    ADD COLUMN pipeline_run_id BIGINT NULL,
    ADD COLUMN sector VARCHAR(64) NULL,
    ADD COLUMN backend VARCHAR(32) NULL;

ALTER TABLE selected_stocks
    ADD CONSTRAINT fk_selected_stocks_pipeline_run
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs (id);

CREATE INDEX ix_selected_stocks_run_score
    ON selected_stocks (pipeline_run_id, ml_score);
