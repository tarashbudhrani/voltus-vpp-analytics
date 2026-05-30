-- =============================================================================
-- BUSINESS QUESTION:
-- How many devices are enrolled per partner, per utility zone, per week?
-- What is week-over-week growth?
--
-- SOURCE TABLE: enrollment_clean (staging table loaded from data/processed/
--               enrollment_clean.parquet after ingestion pipeline)
--
-- NOTE: Partner portal exports are not stored in voltus_internal.db; load the
-- cleaned enrollment file into a staging table before running this query.
-- =============================================================================

-- Expected staging DDL (run once after ingestion):
-- CREATE TABLE enrollment_clean (
--     device_serial           TEXT,
--     partner_name            TEXT,
--     customer_email          TEXT,
--     utility_account_id      TEXT,
--     utility_zone            TEXT,
--     iso_market              TEXT,
--     thermostat_model        TEXT,
--     enrollment_date         TEXT,
--     enrollment_status       TEXT,
--     opt_out_date            TEXT,
--     signup_incentive_paid   INTEGER,
--     annual_incentive_paid   INTEGER,
--     missing_leading_zero_flag INTEGER
-- );

WITH weekly_enrollments AS (
    -- GROUP BY partner / zone / ISO / calendar week: one row per partner-market-week.
    -- Why: operations teams track partner pipeline volume by utility territory
    -- and need a consistent weekly grain for stand-ups and partner scorecards.
    SELECT
        partner_name,
        utility_zone,
        iso_market,
        strftime('%Y-W%W', enrollment_date) AS enroll_week,
        date(enrollment_date, 'weekday 0', '-6 days') AS week_start_date,
        COUNT(*) AS devices_enrolled
    FROM enrollment_clean
    WHERE enrollment_date IS NOT NULL
      AND enrollment_date <> ''
    GROUP BY
        partner_name,
        utility_zone,
        iso_market,
        enroll_week
),

weekly_with_prior AS (
    -- Window function LAG: compare each week to the prior week within the same
    -- partner + utility zone + ISO partition (no JOIN required).
    -- Why: week-over-week growth highlights partner momentum or registration drop-offs.
    SELECT
        partner_name,
        utility_zone,
        iso_market,
        enroll_week,
        week_start_date,
        devices_enrolled,
        LAG(devices_enrolled) OVER (
            PARTITION BY partner_name, utility_zone, iso_market
            ORDER BY week_start_date
        ) AS devices_enrolled_prior_week
    FROM weekly_enrollments
)

SELECT
    partner_name,
    utility_zone,
    iso_market,
    enroll_week,
    week_start_date,
    devices_enrolled,
    devices_enrolled_prior_week,
    devices_enrolled - COALESCE(devices_enrolled_prior_week, 0) AS wow_device_change,
    ROUND(
        100.0 * (devices_enrolled - devices_enrolled_prior_week)
        / NULLIF(devices_enrolled_prior_week, 0),
        1
    ) AS wow_growth_pct
FROM weekly_with_prior
ORDER BY
    partner_name,
    utility_zone,
    iso_market,
    week_start_date;
