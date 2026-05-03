# ADR-0001: Split feature and label persistence into two tables

**Status:** Accepted
**Date:** 2026-05-03

## Context

The XGBoost training pipeline generates ~9M sample rows from 3,049 stocks × rolling 5-day windows. Each row has ~150 feature values (~2KB JSON) plus a binary label. The system must support multiple label methods (e.g., `max_high_5pct`, future methods like moving-average crossover) that produce different label values for the same input window.

Features for a given `(stock_id, input_end_date)` window are invariant — the same 5-day slice of prices and indicators always produces the same feature values. Only labels vary by method.

## Decision

Split into two tables:

**`sample_features`** — keyed by `(stock_id, input_end_date)`:
- `features` (JSON): all ~150 feature values
- `sector` (VARCHAR): denormalized for convenience
- No label columns

**`sample_labels`** — keyed by `(stock_id, input_end_date, label_method)`:
- `label` (SMALLINT): 0 or 1
- `label_method` (VARCHAR): e.g. `"max_high_5pct"`
- `label_version` (VARCHAR): version string from the LabelMethod definition

## Consequences

- **Storage**: With 3 label methods, features stored once (~18GB) instead of duplicated per method (~54GB). Labels table remains negligible.
- **Incremental compute**: Missing features detected by `NOT EXISTS` on `sample_features`. Missing labels detected per-method by `NOT EXISTS` or version mismatch on `sample_labels`.
- **Label method changes**: UPDATE labels for all rows matching the changed method. Features untouched.
- **Query cost**: Training data requires a JOIN between features and labels. Acceptable — training runs infrequently and reads a filtered subset.
- **Inference**: Only reads the latest 5-day window per stock — negligible query difference.

## Alternatives considered

**Single wide table with per-method label columns** — `label_max_high_5pct`, `label_ma_crossover`, etc. Rejected: adding a new method requires ALTER TABLE; columns sparse (only one label value per row, others NULL).

**Single narrow table with features duplicated** — keyed by `(stock_id, input_end_date, label_method)`, JSON features repeated per row. Rejected: ~3× storage cost for 3 methods, growing linearly with each new method.

**Typed feature columns instead of JSON** — each indicator as its own column. Rejected: ~150 columns, rigid schema; adding/removing indicators requires migration. JSON plus indexed key columns is sufficient for the access pattern (always read by `label_method`, not by individual feature values).
