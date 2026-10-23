-- Indexes for TradeShift.
--
-- What it does: adds the indexes the pages need, beyond the primary keys.
--   The metadata-search indexes are what keep Feature 5 under 2 seconds.
-- Inputs: tables from db/schema.sql.
-- Outputs: indexes (IF NOT EXISTS, so safe to re-run).
-- How to run: psql ... -f db/indexes.sql (batch/load_db.py and app/db.py run it for you).

-- Feature 5, metadata search. text_pattern_ops lets "hs6 LIKE '8450%'" (search by
-- HS4 or HS2 prefix) use the index; created_at serves "in the last 6 months".
CREATE INDEX IF NOT EXISTS analyses_hs6_idx      ON analyses (hs6 text_pattern_ops);
CREATE INDEX IF NOT EXISTS analyses_created_idx  ON analyses (created_at DESC);
CREATE INDEX IF NOT EXISTS analyses_importer_idx ON analyses (importer);
CREATE INDEX IF NOT EXISTS analyses_supplier_idx ON analyses (supplier);
CREATE INDEX IF NOT EXISTS analyses_event_idx    ON analyses (event_id);

CREATE INDEX IF NOT EXISTS notes_target_idx   ON notes (target_type, target_id);
CREATE INDEX IF NOT EXISTS notes_hs6_idx      ON notes (hs6 text_pattern_ops);
CREATE INDEX IF NOT EXISTS notes_created_idx  ON notes (created_at DESC);
CREATE INDEX IF NOT EXISTS notes_importer_idx ON notes (importer);
CREATE INDEX IF NOT EXISTS notes_supplier_idx ON notes (supplier);
CREATE INDEX IF NOT EXISTS notes_event_idx    ON notes (event_id);

-- Compare view: one supplier across many products / importers.
CREATE INDEX IF NOT EXISTS trade_supplier_idx ON trade_monthly (importer, supplier, hs6);

-- Detector, top movers and product pages.
CREATE INDEX IF NOT EXISTS signals_event_idx    ON signals (event_id);
CREATE INDEX IF NOT EXISTS signals_value_idx    ON signals (value_redirected_usd DESC);
CREATE INDEX IF NOT EXISTS signals_hs6_idx      ON signals (hs6);
CREATE INDEX IF NOT EXISTS event_products_hs6_idx ON event_products (hs6);
CREATE INDEX IF NOT EXISTS products_hs4_idx     ON products (hs4);
CREATE INDEX IF NOT EXISTS products_desc_idx    ON products (lower(description) text_pattern_ops);
