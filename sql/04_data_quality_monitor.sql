-- =============================================================================
-- BUSINESS QUESTION:
-- For each event, what percent of interval meter reads were actual vs estimated
-- vs missing? Flag events where missing read rate exceeds 5% (manual follow-up).
--
-- SOURCE TABLE: interval_clean (staging table loaded from data/processed/
--               interval_clean.parquet after ingestion pipeline)
--
-- FLAG LEGEND (data_quality_flag):
--   A = actual read from meter
--   E = estimated read (utility imputed value)
--   M = missing read (interval absent from file — comm failure or gap)
-- =============================================================================

-- Expected staging DDL (run once after ingestion):
-- CREATE TABLE interval_clean (
--     utility_account_id   TEXT,
--     meter_id               TEXT,
--     interval_start_local   TEXT,
--     interval_start_utc     TEXT,
--     usage_kwh              REAL,
--     data_quality_flag      TEXT,
--     event_id               INTEGER,
--     is_event_window        INTEGER,
--     source_file            TEXT,
--     is_error               INTEGER,
--     intervals_expected     INTEGER,
--     intervals_actual       INTEGER
-- );

WITH account_event_summary AS (
    -- GROUP BY event + account + meter: derive expected vs actual interval counts
    -- at the meter level (deduplicated because each interval row repeats these totals).
    -- Why: missing reads are defined as the gap between what the utility should have
    -- delivered and what appears in the post-event download.
    SELECT
        event_id,
        source_file,
        utility_account_id,
        meter_id,
        MAX(intervals_expected) AS intervals_expected,
        MAX(intervals_actual)   AS intervals_actual
    FROM interval_clean
    GROUP BY
        event_id,
        source_file,
        utility_account_id,
        meter_id
),

event_missing AS (
    SELECT
        event_id,
        source_file,
        SUM(intervals_expected) AS total_expected_intervals,
        SUM(intervals_actual)   AS total_actual_intervals,
        SUM(intervals_expected - intervals_actual) AS total_missing_intervals
    FROM account_event_summary
    GROUP BY event_id, source_file
),

event_quality_flags AS (
    -- COUNT rows by data_quality_flag per event (actual vs estimated reads present).
    -- Why: estimated reads (E) indicate AMI gaps the utility filled algorithmically.
    SELECT
        event_id,
        source_file,
        COUNT(*) AS total_interval_rows,
        SUM(CASE WHEN data_quality_flag = 'A' THEN 1 ELSE 0 END) AS actual_reads,
        SUM(CASE WHEN data_quality_flag = 'E' THEN 1 ELSE 0 END) AS estimated_reads
    FROM interval_clean
    GROUP BY event_id, source_file
)

SELECT
    q.event_id,
    q.source_file,

    -- JOIN event_missing → event_quality_flags via event_id + source_file:
    -- combine row-level quality flags with meter-level missing interval counts.
    -- Why: a complete data quality picture needs both flag distribution and comm gaps.
    q.total_interval_rows,
    q.actual_reads,
    q.estimated_reads,
    m.total_missing_intervals,

    ROUND(100.0 * q.actual_reads    / NULLIF(q.total_interval_rows, 0), 1) AS pct_actual,
    ROUND(100.0 * q.estimated_reads / NULLIF(q.total_interval_rows, 0), 1) AS pct_estimated,
    ROUND(
        100.0 * m.total_missing_intervals / NULLIF(m.total_expected_intervals, 0),
        1
    ) AS pct_missing,

    CASE
        WHEN 100.0 * m.total_missing_intervals / NULLIF(m.total_expected_intervals, 0) > 5.0
        THEN 1 ELSE 0
    END AS needs_manual_followup

FROM event_quality_flags q
INNER JOIN event_missing m
    ON m.event_id = q.event_id
   AND m.source_file = q.source_file
ORDER BY q.event_id;
