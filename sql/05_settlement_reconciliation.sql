-- =============================================================================
-- BUSINESS QUESTION:
-- For each customer per event, what was baseline usage vs actual usage during
-- the event window? Reduction = baseline - actual. Revenue = reduction_kw *
-- capacity_rate_per_kw. Flag customers where usage went UP during the event.
--
-- SOURCE TABLES:
--   interval_clean  (staging — meter interval reads)
--   customers, enrollments, programs  (voltus_internal.db)
--
-- JOIN PATH:
--   interval_clean.utility_account_id → customers.utility_account_number
--   customers.voltus_customer_id → enrollments.voltus_customer_id
--   enrollments.program_id → programs.program_id (for $/kW rate)
-- =============================================================================

-- Interval window length in hours (15-minute reads).
-- baseline_kw and event_kw convert kWh totals to average kW over each window.

WITH baseline_usage AS (
    SELECT
        utility_account_id,
        event_id,
        COUNT(*) AS baseline_intervals,
        SUM(usage_kwh) AS baseline_kwh
    FROM interval_clean
    WHERE is_event_window = 0
      AND COALESCE(is_error, 0) = 0
    GROUP BY utility_account_id, event_id
),

event_window_usage AS (
    SELECT
        utility_account_id,
        event_id,
        COUNT(*) AS event_intervals,
        SUM(usage_kwh) AS event_kwh
    FROM interval_clean
    WHERE is_event_window = 1
      AND COALESCE(is_error, 0) = 0
    GROUP BY utility_account_id, event_id
),

usage_comparison AS (
    -- JOIN baseline → event window on account + event: align pre-event and
    -- during-event consumption for the same meter account.
    -- Why: curtailment is measured as the drop from baseline to event-window load.
    SELECT
        b.utility_account_id,
        b.event_id,
        b.baseline_kwh,
        e.event_kwh,
        b.baseline_intervals,
        e.event_intervals,

        -- Convert kWh totals to average kW (each interval = 0.25 hours).
        b.baseline_kwh / (b.baseline_intervals * 0.25) AS baseline_kw,
        e.event_kwh    / (e.event_intervals    * 0.25) AS event_kw

    FROM baseline_usage b
    INNER JOIN event_window_usage e
        ON e.utility_account_id = b.utility_account_id
       AND e.event_id = b.event_id
),

settlement_base AS (
    -- JOIN usage → customers on utility account: link meter data to Voltus customer.
    -- Why: settlement pays customers, not anonymous meter IDs.
    SELECT
        u.utility_account_id,
        u.event_id,
        c.voltus_customer_id,
        c.full_name,
        c.utility_name,
        u.baseline_kwh,
        u.event_kwh,
        u.baseline_kw,
        u.event_kw,
        u.baseline_kw - u.event_kw AS reduction_kw
    FROM usage_comparison u
    INNER JOIN customers c
        ON c.utility_account_number = u.utility_account_id
        OR ltrim(c.utility_account_number, '0') = ltrim(u.utility_account_id, '0')
),

settlement_with_rates AS (
    -- JOIN customers → enrollments → programs: attach the capacity rate for the
    -- program the customer is enrolled in (matched to the event's program where possible).
    -- Why: revenue share depends on program tariff ($/kW), not a flat rate.
    SELECT
        sb.utility_account_id,
        sb.event_id,
        sb.voltus_customer_id,
        sb.full_name,
        sb.utility_name,
        p.program_name,
        p.capacity_rate_per_kw,
        ev.event_date,
        sb.baseline_kwh,
        sb.event_kwh,
        sb.baseline_kw,
        sb.event_kw,
        sb.reduction_kw,
        sb.reduction_kw * p.capacity_rate_per_kw AS revenue_usd,
        CASE WHEN sb.reduction_kw < 0 THEN 1 ELSE 0 END AS negative_reduction_flag
    FROM settlement_base sb
    INNER JOIN enrollments en
        ON en.voltus_customer_id = sb.voltus_customer_id
    INNER JOIN programs p
        ON p.program_id = en.program_id
    INNER JOIN dr_events ev
        ON ev.event_id = sb.event_id
       AND ev.program_id = en.program_id
)

SELECT
    event_id,
    event_date,
    voltus_customer_id,
    full_name,
    utility_account_id,
    utility_name,
    program_name,
    ROUND(baseline_kwh, 3)  AS baseline_kwh,
    ROUND(event_kwh, 3)     AS event_kwh,
    ROUND(baseline_kw, 3)   AS baseline_kw,
    ROUND(event_kw, 3)      AS event_kw,
    ROUND(reduction_kw, 3)  AS reduction_kw,
    ROUND(revenue_usd, 2)   AS revenue_usd,
    negative_reduction_flag
FROM settlement_with_rates
ORDER BY event_id, voltus_customer_id;
