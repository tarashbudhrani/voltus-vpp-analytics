-- Voltus internal operational database schema

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS partners (
    partner_id INTEGER PRIMARY KEY,
    partner_name TEXT NOT NULL,
    api_endpoint TEXT,
    contract_start_date TEXT NOT NULL,
    revenue_share_pct REAL NOT NULL,
    contact_email TEXT
);

CREATE TABLE IF NOT EXISTS customers (
    voltus_customer_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT,
    address TEXT,
    city TEXT,
    state TEXT NOT NULL,
    zip TEXT,
    utility_account_number TEXT,
    utility_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS programs (
    program_id INTEGER PRIMARY KEY,
    program_name TEXT NOT NULL,
    iso_market TEXT NOT NULL,
    utility_name TEXT NOT NULL,
    program_type TEXT NOT NULL CHECK (
        program_type IN ('capacity_dr', 'economic_dr', 'emergency_event')
    ),
    capacity_rate_per_kw REAL,
    season TEXT
);

CREATE TABLE IF NOT EXISTS enrollments (
    enrollment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    voltus_customer_id TEXT NOT NULL,
    program_id INTEGER NOT NULL,
    partner_id INTEGER NOT NULL,
    enrolled_date TEXT NOT NULL,
    status TEXT NOT NULL,
    capacity_kw TEXT,
    notes TEXT,
    FOREIGN KEY (voltus_customer_id) REFERENCES customers (voltus_customer_id),
    FOREIGN KEY (program_id) REFERENCES programs (program_id),
    FOREIGN KEY (partner_id) REFERENCES partners (partner_id)
);

CREATE TABLE IF NOT EXISTS dr_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    event_date TEXT NOT NULL,
    event_start_time TEXT NOT NULL,
    event_end_time TEXT NOT NULL,
    iso_market TEXT NOT NULL,
    mw_called REAL NOT NULL,
    mw_delivered REAL,
    event_type TEXT NOT NULL,
    temperature_f REAL,
    FOREIGN KEY (program_id) REFERENCES programs (program_id)
);

CREATE INDEX IF NOT EXISTS idx_customers_email ON customers (email);
CREATE INDEX IF NOT EXISTS idx_customers_utility_account ON customers (utility_account_number);
CREATE INDEX IF NOT EXISTS idx_enrollments_customer ON enrollments (voltus_customer_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_program ON enrollments (program_id);
CREATE INDEX IF NOT EXISTS idx_dr_events_date ON dr_events (event_date);
