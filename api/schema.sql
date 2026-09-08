CREATE SCHEMA IF NOT EXISTS xm;

CREATE TABLE IF NOT EXISTS xm.users (
    id uuid PRIMARY KEY,
    email text NOT NULL UNIQUE,
    display_name text NOT NULL,
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS xm.sessions (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES xm.users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON xm.sessions(expires_at);

CREATE TABLE IF NOT EXISTS xm.user_preferences (
    user_id uuid PRIMARY KEY REFERENCES xm.users(id) ON DELETE CASCADE,
    preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS xm.imports (
    id uuid PRIMARY KEY,
    company_id text NOT NULL DEFAULT 'xm',
    agent_name text NOT NULL,
    file_name text NOT NULL,
    file_path text NOT NULL,
    file_sha256 text NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    total_messages integer NOT NULL DEFAULT 0,
    processed_messages integer NOT NULL DEFAULT 0,
    request_count integer NOT NULL DEFAULT 0,
    listing_count integer NOT NULL DEFAULT 0,
    ignored_count integer NOT NULL DEFAULT 0,
    duplicate_count integer NOT NULL DEFAULT 0,
    qdrant_points integer NOT NULL DEFAULT 0,
    error text,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id, agent_name, file_sha256)
);

CREATE TABLE IF NOT EXISTS xm.raw_messages (
    id uuid PRIMARY KEY,
    company_id text NOT NULL DEFAULT 'xm',
    agent_name text NOT NULL,
    import_id uuid NOT NULL REFERENCES xm.imports(id) ON DELETE CASCADE,
    chat_id text NOT NULL,
    chat_name text NOT NULL,
    is_group boolean NOT NULL DEFAULT false,
    message_position integer NOT NULL,
    sent_at timestamp,
    author text,
    raw_text text NOT NULL,
    message_hash text NOT NULL,
    classification text NOT NULL,
    confidence numeric(5,4) NOT NULL DEFAULT 0,
    duplicate_of uuid,
    extracted jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(import_id, chat_id, message_position)
);

CREATE INDEX IF NOT EXISTS raw_messages_import_idx ON xm.raw_messages(import_id);
CREATE INDEX IF NOT EXISTS raw_messages_classification_idx ON xm.raw_messages(company_id, classification);
CREATE INDEX IF NOT EXISTS raw_messages_hash_idx ON xm.raw_messages(company_id, message_hash);

CREATE TABLE IF NOT EXISTS xm.documents (
    id uuid PRIMARY KEY,
    company_id text NOT NULL DEFAULT 'xm',
    agent_name text NOT NULL,
    raw_message_id uuid NOT NULL REFERENCES xm.raw_messages(id) ON DELETE CASCADE,
    import_id uuid NOT NULL REFERENCES xm.imports(id) ON DELETE CASCADE,
    document_type text NOT NULL CHECK (document_type IN ('buyer_request', 'property_listing')),
    transaction_type text NOT NULL DEFAULT 'unknown',
    categories text[] NOT NULL DEFAULT '{}',
    primary_category text,
    locations text[] NOT NULL DEFAULT '{}',
    land_area_min numeric,
    land_area_max numeric,
    building_area_min numeric,
    building_area_max numeric,
    price_min bigint,
    price_max bigint,
    price_basis text,
    negotiable boolean NOT NULL DEFAULT false,
    facing text[] NOT NULL DEFAULT '{}',
    exclusions text[] NOT NULL DEFAULT '{}',
    requirements text[] NOT NULL DEFAULT '{}',
    contact_name text,
    contact_phone text,
    normalized_text text NOT NULL,
    extraction_confidence numeric(5,4) NOT NULL DEFAULT 0,
    review_status text NOT NULL DEFAULT 'auto',
    active boolean NOT NULL DEFAULT true,
    qdrant_point_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS documents_type_idx ON xm.documents(company_id, document_type, active);
CREATE INDEX IF NOT EXISTS documents_category_idx ON xm.documents USING gin(categories);
CREATE INDEX IF NOT EXISTS documents_locations_idx ON xm.documents USING gin(locations);
CREATE INDEX IF NOT EXISTS documents_import_idx ON xm.documents(import_id);

CREATE OR REPLACE VIEW xm.buyer_requests AS
SELECT * FROM xm.documents WHERE document_type = 'buyer_request';

CREATE OR REPLACE VIEW xm.property_listings AS
SELECT * FROM xm.documents WHERE document_type = 'property_listing';

CREATE TABLE IF NOT EXISTS xm.match_settings (
    company_id text PRIMARY KEY,
    land_tolerance_pct numeric NOT NULL DEFAULT 10,
    building_tolerance_pct numeric NOT NULL DEFAULT 20,
    price_tolerance_pct numeric NOT NULL DEFAULT 10,
    location_radius_km numeric NOT NULL DEFAULT 3,
    location_extended_radius_km numeric NOT NULL DEFAULT 5,
    location_weight_pct numeric NOT NULL DEFAULT 35,
    land_weight_pct numeric NOT NULL DEFAULT 20,
    building_weight_pct numeric NOT NULL DEFAULT 15,
    price_weight_pct numeric NOT NULL DEFAULT 20,
    semantic_weight_pct numeric NOT NULL DEFAULT 5,
    data_quality_weight_pct numeric NOT NULL DEFAULT 5,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO xm.match_settings(company_id)
VALUES ('xm') ON CONFLICT (company_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS xm.matches (
    id uuid PRIMARY KEY,
    company_id text NOT NULL DEFAULT 'xm',
    buyer_request_id uuid NOT NULL REFERENCES xm.documents(id) ON DELETE CASCADE,
    property_listing_id uuid NOT NULL REFERENCES xm.documents(id) ON DELETE CASCADE,
    score numeric(6,2) NOT NULL,
    location_score numeric(6,2) NOT NULL DEFAULT 0,
    land_score numeric(6,2) NOT NULL DEFAULT 0,
    building_score numeric(6,2) NOT NULL DEFAULT 0,
    price_score numeric(6,2) NOT NULL DEFAULT 0,
    semantic_score numeric(6,2) NOT NULL DEFAULT 0,
    explanation jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(company_id, buyer_request_id, property_listing_id)
);

CREATE INDEX IF NOT EXISTS matches_buyer_score_idx ON xm.matches(company_id, buyer_request_id, score DESC);
CREATE INDEX IF NOT EXISTS matches_score_idx ON xm.matches(company_id, score DESC);
CREATE INDEX IF NOT EXISTS matches_listing_idx ON xm.matches(property_listing_id);

CREATE TABLE IF NOT EXISTS xm.audit_events (
    id bigserial PRIMARY KEY,
    company_id text NOT NULL DEFAULT 'xm',
    event_type text NOT NULL,
    entity_type text,
    entity_id text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS xm.glossary (
  alias text PRIMARY KEY, canonical text NOT NULL
);
INSERT INTO xm.glossary(alias, canonical) VALUES
('regensi','regency'),('rgcy','regency'),('nashos','national hospital'),('nathos','national hospital')
ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS xm.maintenance_jobs (
 id uuid PRIMARY KEY, status text NOT NULL DEFAULT 'queued', result jsonb, error text,
 created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS maintenance_one_running ON xm.maintenance_jobs ((true)) WHERE status IN ('queued','processing');

ALTER TABLE xm.documents ADD COLUMN IF NOT EXISTS contact_phones text[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS documents_recent_idx ON xm.documents(company_id,created_at DESC) WHERE active;

ALTER TABLE xm.match_settings ADD COLUMN IF NOT EXISTS location_weight_pct numeric NOT NULL DEFAULT 35;
ALTER TABLE xm.match_settings ADD COLUMN IF NOT EXISTS land_weight_pct numeric NOT NULL DEFAULT 20;
ALTER TABLE xm.match_settings ADD COLUMN IF NOT EXISTS building_weight_pct numeric NOT NULL DEFAULT 15;
ALTER TABLE xm.match_settings ADD COLUMN IF NOT EXISTS price_weight_pct numeric NOT NULL DEFAULT 20;
ALTER TABLE xm.match_settings ADD COLUMN IF NOT EXISTS semantic_weight_pct numeric NOT NULL DEFAULT 5;
ALTER TABLE xm.match_settings ADD COLUMN IF NOT EXISTS data_quality_weight_pct numeric NOT NULL DEFAULT 5;
