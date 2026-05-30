-- =============================================================================
-- BUSINESS QUESTION:
-- How many customers are at each stage of the enrollment funnel?
--
-- FUNNEL STAGES (cumulative):
--   lead_captured → utility_data_authorized → market_registered →
--   active_enrolled → event_participated → retained_12mo
--
-- SOURCE TABLES: customers, enrollments, dr_events (+ programs for event linkage)
-- DATABASE: voltus_internal.db
-- =============================================================================

WITH enrolled_customers AS (
    -- JOIN enrollments → customers: attach every enrollment to its customer profile.
    -- Why: funnel stages after "market_registered" are defined at the customer level.
    SELECT
        c.voltus_customer_id,
        c.created_at,
        c.utility_account_number,
        e.enrollment_id,
        e.program_id,
        e.enrolled_date,
        e.status
    FROM customers c
    LEFT JOIN enrollments e
        ON e.voltus_customer_id = c.voltus_customer_id
),

event_participants AS (
    -- JOIN enrollments → dr_events via program_id: find customers eligible to participate
    -- in each dispatch event (enrolled on or before the event date with active status).
    -- Why: "event_participated" means the customer was actively enrolled in the program
    -- that was called for a summer DR event.
    SELECT DISTINCT
        ec.voltus_customer_id
    FROM enrolled_customers ec
    INNER JOIN dr_events ev
        ON ev.program_id = ec.program_id
    WHERE ec.status = 'active'
      AND date(ec.enrolled_date) <= date(ev.event_date)
),

funnel_flags AS (
    SELECT
        ec.voltus_customer_id,

        -- Stage 1: customer exists in Voltus CRM (lead captured from partner or direct).
        1 AS is_lead_captured,

        -- Stage 2: utility account number on file (utility data sharing authorized).
        CASE
            WHEN ec.utility_account_number IS NOT NULL
             AND trim(ec.utility_account_number) <> ''
            THEN 1 ELSE 0
        END AS is_utility_data_authorized,

        -- Stage 3: enrolled in at least one DR program (market registration complete).
        CASE
            WHEN ec.enrollment_id IS NOT NULL THEN 1 ELSE 0
        END AS is_market_registered,

        -- Stage 4: currently active in a program.
        CASE
            WHEN ec.status = 'active' THEN 1 ELSE 0
        END AS is_active_enrolled,

        -- Stage 5: participated in at least one DR event (active on event date).
        CASE
            WHEN ep.voltus_customer_id IS NOT NULL THEN 1 ELSE 0
        END AS is_event_participated,

        -- Stage 6: retained 12+ months — still active and enrolled over a year ago.
        CASE
            WHEN ec.status = 'active'
             AND julianday('now') - julianday(ec.enrolled_date) >= 365
            THEN 1 ELSE 0
        END AS is_retained_12mo

    FROM enrolled_customers ec
    LEFT JOIN event_participants ep
        ON ep.voltus_customer_id = ec.voltus_customer_id
)

SELECT
    stage,
    customer_count,
    ROUND(100.0 * customer_count / MAX(customer_count) OVER (), 1) AS pct_of_leads
FROM (
    SELECT 'lead_captured'           AS stage, SUM(is_lead_captured)           AS customer_count FROM funnel_flags
    UNION ALL
    SELECT 'utility_data_authorized', SUM(is_utility_data_authorized)         FROM funnel_flags
    UNION ALL
    SELECT 'market_registered',       SUM(is_market_registered)               FROM funnel_flags
    UNION ALL
    SELECT 'active_enrolled',         SUM(is_active_enrolled)                 FROM funnel_flags
    UNION ALL
    SELECT 'event_participated',      SUM(is_event_participated)              FROM funnel_flags
    UNION ALL
    SELECT 'retained_12mo',           SUM(is_retained_12mo)                   FROM funnel_flags
)
ORDER BY
    CASE stage
        WHEN 'lead_captured'           THEN 1
        WHEN 'utility_data_authorized' THEN 2
        WHEN 'market_registered'       THEN 3
        WHEN 'active_enrolled'         THEN 4
        WHEN 'event_participated'      THEN 5
        WHEN 'retained_12mo'           THEN 6
    END;
