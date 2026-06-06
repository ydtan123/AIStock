-- Per-step status tracking for pipeline_runs
-- 4 steps x 3 columns = 12 columns, all nullable for backward compatibility
ALTER TABLE pipeline_runs
    ADD COLUMN data_update_status VARCHAR(20) NULL,
    ADD COLUMN data_update_started_at DATETIME NULL,
    ADD COLUMN data_update_finished_at DATETIME NULL,
    ADD COLUMN stock_selection_status VARCHAR(20) NULL,
    ADD COLUMN stock_selection_started_at DATETIME NULL,
    ADD COLUMN stock_selection_finished_at DATETIME NULL,
    ADD COLUMN fast_evaluation_status VARCHAR(20) NULL,
    ADD COLUMN fast_evaluation_started_at DATETIME NULL,
    ADD COLUMN fast_evaluation_finished_at DATETIME NULL,
    ADD COLUMN deep_evaluation_status VARCHAR(20) NULL,
    ADD COLUMN deep_evaluation_started_at DATETIME NULL,
    ADD COLUMN deep_evaluation_finished_at DATETIME NULL;
