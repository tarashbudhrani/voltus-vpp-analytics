-- =============================================================================
-- BUSINESS QUESTION:
-- For each DR event, what MW was called vs delivered?
-- What percent of enrolled customers responded?
--
-- SOURCE TABLES: dr_events, enrollments, programs
-- DATABASE: voltus_internal.db
-- =============================================================================

WITH event_enrollments AS (
    -- JOIN dr_events → programs → enrollments via program_id: pull all customers
    -- enrolled in the program that was dispatched for this event.
    -- Why: response rate denominator = enrolled population for that program/market.
    SELECT
        ev.event_id,
        ev.event_date,
        ev.iso_market,
        ev.event_type,
        ev.mw_called,
        ev.mw_delivered,
        ev.temperature_f,
        p.program_name,
        en.enrollment_id,
        en.voltus_customer_id,
        en.enrolled_date,
        en.status
    FROM dr_events ev
    INNER JOIN programs p
        ON p.program_id = ev.program_id
    INNER JOIN enrollments en
        ON en.program_id = ev.program_id
),

event_metrics AS (
    SELECT
        event_id,
        event_date,
        iso_market,
        event_type,
        program_name,
        mw_called,
        mw_delivered,
        temperature_f,

        -- Portfolio performance: did we deliver the MW the ISO called?
        ROUND(100.0 * mw_delivered / NULLIF(mw_called, 0), 1) AS performance_pct,

        -- Denominator: customers enrolled in the program before the event.
        COUNT(DISTINCT CASE
            WHEN date(enrolled_date) <= date(event_date)
            THEN voltus_customer_id
        END) AS enrolled_customers,

        -- Numerator: actively enrolled customers on the event date (responded / eligible).
        COUNT(DISTINCT CASE
            WHEN status = 'active'
             AND date(enrolled_date) <= date(event_date)
            THEN voltus_customer_id
        END) AS responded_customers

    FROM event_enrollments
    GROUP BY
        event_id,
        event_date,
        iso_market,
        event_type,
        program_name,
        mw_called,
        mw_delivered,
        temperature_f
)

SELECT
    event_id,
    event_date,
    iso_market,
    event_type,
    program_name,
    mw_called,
    mw_delivered,
    performance_pct,
    enrolled_customers,
    responded_customers,
    ROUND(
        100.0 * responded_customers / NULLIF(enrolled_customers, 0),
        1
    ) AS customer_response_pct,
    temperature_f
FROM event_metrics
ORDER BY event_date;
