-- TradeShift database schema (RDS PostgreSQL).
--
-- What it does: creates every table if it does not exist yet. Safe to run any
--   number of times, so both the batch server and every web server run it at start.
-- Inputs: none.
-- Outputs: tables in the "tradeshift" database.
-- How to run: psql -h $DB_HOST -U tradeshift -d tradeshift -f db/schema.sql
--   (the pipeline and the app run it for you via load_db.py / db.py).
--
-- Two kinds of table:
--   * Pipeline tables are rebuilt by batch/load_db.py on every run (truncate + load),
--     so running the pipeline twice never duplicates data.
--   * App tables (analyses, notes) hold user work and are never truncated.
--
-- Codes use varchar, not char: char pads with spaces, which breaks prefix search.
-- Months are stored as 'YYYY-MM' text: they sort correctly, join directly with
-- the pipeline files, and need no time-zone handling.

-- ---------------------------------------------------------------- reference
CREATE TABLE IF NOT EXISTS countries (
    iso2          varchar(3) PRIMARY KEY,   -- ISO alpha-2, plus 'ROW' for rest of world
    name          text NOT NULL,
    census_code   varchar(4),
    comtrade_code varchar(4),
    is_eu         boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS products (
    hs6         varchar(6) PRIMARY KEY,
    hs4         varchar(4) NOT NULL,
    description text,
    revised_in  varchar(7)                     -- HS revision month if the code started/stopped then
);

CREATE TABLE IF NOT EXISTS tariff_events (
    event_id           text PRIMARY KEY,
    name               text NOT NULL,
    measure            text NOT NULL,
    tariffed_suppliers text,
    exempt_suppliers   text,
    tariff_rate        text,
    announced_date     date,
    effective_date     date NOT NULL,
    hs_version         text,
    source_url         text NOT NULL,
    notes              text
);

CREATE TABLE IF NOT EXISTS tariff_event_products (
    event_id   text NOT NULL,
    hts8       varchar(8),
    hs6        varchar(6) NOT NULL,
    coverage   text,
    source_url text
);

-- ---------------------------------------------------------------- trade data
CREATE TABLE IF NOT EXISTS trade_monthly (
    importer  varchar(3) NOT NULL,
    supplier  varchar(3) NOT NULL,
    hs6       varchar(6)    NOT NULL,
    month     varchar(7)    NOT NULL,
    value_usd double precision NOT NULL,
    qty       double precision,
    qty_unit  text,
    PRIMARY KEY (importer, hs6, month, supplier)
);

CREATE TABLE IF NOT EXISTS hhi_monthly (
    importer    varchar(3) NOT NULL,
    hs6         varchar(6)    NOT NULL,
    month       varchar(7)    NOT NULL,
    total_value double precision,
    n_suppliers integer,
    hhi         double precision,
    hhi_12m     double precision,
    PRIMARY KEY (importer, hs6, month)
);

CREATE TABLE IF NOT EXISTS totals_check (
    month        varchar(7) PRIMARY KEY,
    census_total double precision,
    country_sum  double precision,
    diff_pct     double precision
);

-- ---------------------------------------------------------------- signals
CREATE TABLE IF NOT EXISTS event_shares (
    event_id      text       NOT NULL,
    hs6           varchar(6)    NOT NULL,
    supplier      varchar(3) NOT NULL,
    value_before  double precision,
    share_before  double precision,
    qshare_before double precision,
    value_after   double precision,
    share_after   double precision,
    qshare_after  double precision,
    tariffed      boolean NOT NULL,
    PRIMARY KEY (event_id, hs6, supplier)
);

CREATE TABLE IF NOT EXISTS event_products (
    event_id     text    NOT NULL,
    hs6          varchar(6) NOT NULL,
    total_before double precision,
    total_after  double precision,
    hhi_before   double precision,
    hhi_after    double precision,
    hs_changed   boolean,
    before_start varchar(7),
    after_end    varchar(7),
    PRIMARY KEY (event_id, hs6)
);

CREATE TABLE IF NOT EXISTS signals (
    id                   serial PRIMARY KEY,
    event_id             text    NOT NULL,
    hs6                  varchar(6) NOT NULL,
    loser                varchar(3) NOT NULL,
    gainer               varchar(3) NOT NULL,
    loser_share_before   double precision,
    loser_share_after    double precision,
    gainer_share_before  double precision,
    gainer_share_after   double precision,
    drop_pp              double precision,
    gain_pp              double precision,
    value_redirected_usd double precision,
    total_before_usd     double precision,
    total_after_usd      double precision,
    total_change_pct     double precision,
    confidence           text,
    hhi_before           double precision,
    hhi_after            double precision,
    hs_changed           boolean,
    pattern              text,
    explanation          text,
    source_url           text,
    data_url             text
);

CREATE TABLE IF NOT EXISTS did_results (
    event_id  text PRIMARY KEY,
    n_treated integer,
    n_control integer,
    beta_pp   double precision,
    se_pp     double precision,
    t_stat    double precision,
    p_value   double precision,
    n_obs     integer
);

-- Singapore lens. Estimated re-exports = Singapore's exports to the US (Comtrade)
-- minus US imports of Singapore-origin goods (Census); see batch/clean.py.
CREATE TABLE IF NOT EXISTS singapore_monthly (
    hs6                      varchar(6) NOT NULL,
    month                    varchar(7) NOT NULL,
    sg_exports_usd           double precision,
    us_imports_sg_origin_usd double precision,
    est_reexports_usd        double precision,
    PRIMARY KEY (hs6, month)
);

-- SingStat's official re-exports (RX) and domestic exports (DX) to the US, all products, in US$.
CREATE TABLE IF NOT EXISTS singapore_official (
    month  varchar(7) PRIMARY KEY,
    rx_usd double precision,
    dx_usd double precision
);

CREATE TABLE IF NOT EXISTS singapore_lens (
    hs6                    varchar(6) PRIMARY KEY,
    event_id               text,
    exports_before         double precision,
    exports_after          double precision,
    origin_before          double precision,
    origin_after           double precision,
    est_rx_before          double precision,
    est_rx_after           double precision,
    est_rx_growth_pct      double precision,
    est_rx_share_after_pct double precision,
    cn_share_before        double precision,
    cn_share_after         double precision,
    flagged                boolean
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          serial PRIMARY KEY,
    step        text NOT NULL,
    status      text NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    detail      text
);

-- ---------------------------------------------------------------- app tables (never truncated)
-- Feature 3 + 5: one row per saved analysis. The analysis itself is a Markdown file
-- in S3 (s3_key); this row holds the metadata that the Search page filters on.
CREATE TABLE IF NOT EXISTS analyses (
    id          uuid PRIMARY KEY,
    title       text NOT NULL,
    view        text NOT NULL,
    s3_key      text NOT NULL,
    hs6         varchar(6),
    importer    varchar(3),
    supplier    varchar(3),
    event_id    text,
    params      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    instance_id text
);

-- Feature 4 + 5: notes on a product or a saved analysis, with the same metadata.
CREATE TABLE IF NOT EXISTS notes (
    id          serial PRIMARY KEY,
    target_type text NOT NULL CHECK (target_type IN ('product', 'analysis')),
    target_id   text NOT NULL,             -- hs6 for products, analysis uuid for analyses
    hs6         varchar(6),
    importer    varchar(3),
    supplier    varchar(3),
    event_id    text,
    body        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    instance_id text
);
