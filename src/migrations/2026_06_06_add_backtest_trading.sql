-- Add backtest + trading per-step status columns to pipeline_runs
ALTER TABLE pipeline_runs ADD COLUMN backtest_status VARCHAR(20) NULL;
ALTER TABLE pipeline_runs ADD COLUMN backtest_started_at DATETIME NULL;
ALTER TABLE pipeline_runs ADD COLUMN backtest_finished_at DATETIME NULL;
ALTER TABLE pipeline_runs ADD COLUMN trading_status VARCHAR(20) NULL;
ALTER TABLE pipeline_runs ADD COLUMN trading_started_at DATETIME NULL;
ALTER TABLE pipeline_runs ADD COLUMN trading_finished_at DATETIME NULL;

-- Backtest results table (one row per pipeline run)
CREATE TABLE IF NOT EXISTS backtest_results (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    pipeline_run_id BIGINT NOT NULL,
    annual_return DOUBLE NULL,
    sharpe_ratio DOUBLE NULL,
    sortino_ratio DOUBLE NULL,
    max_drawdown DOUBLE NULL,
    volatility DOUBLE NULL,
    calmar_ratio DOUBLE NULL,
    start_date VARCHAR(20) NULL,
    end_date VARCHAR(20) NULL,
    initial_capital DOUBLE NULL,
    final_value DOUBLE NULL,
    num_tickers INT NULL,
    benchmark_metrics TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_br_run (pipeline_run_id),
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id)
);

-- Trading results table (one row per pipeline run)
CREATE TABLE IF NOT EXISTS trading_results (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    pipeline_run_id BIGINT NOT NULL,
    execution_mode VARCHAR(20) NOT NULL DEFAULT 'dry_run',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    buys INT NULL,
    sells INT NULL,
    orders_json TEXT NULL,
    portfolio_before_json TEXT NULL,
    error_message TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_tr_run (pipeline_run_id),
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id)
);
