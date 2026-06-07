-- Trading step: online_transaction + portfolio tables
CREATE TABLE IF NOT EXISTS online_transaction (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    pipeline_run_id BIGINT NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    action VARCHAR(4) NOT NULL COMMENT 'BUY or SELL',
    shares DECIMAL(15,6) NOT NULL,
    price DECIMAL(15,4) NOT NULL,
    total_amount DECIMAL(20,2) NOT NULL COMMENT 'cost for BUY, proceeds for SELL',
    remaining_cash DECIMAL(20,2) NOT NULL COMMENT 'projected cash after this transaction',
    status VARCHAR(10) NOT NULL DEFAULT 'planned' COMMENT 'planned | submitted | filled',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_ot_run (pipeline_run_id),
    INDEX ix_ot_ticker (ticker),
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id)
);

CREATE TABLE IF NOT EXISTS portfolio (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    pipeline_run_id BIGINT NOT NULL,
    ticker VARCHAR(10) NULL,
    shares DECIMAL(15,6) NULL,
    avg_cost DECIMAL(15,4) NULL,
    cash DECIMAL(20,2) NOT NULL DEFAULT 0,
    equity DECIMAL(20,2) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_pf_run (pipeline_run_id),
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id)
);
