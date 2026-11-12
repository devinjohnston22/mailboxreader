CREATE SCHEMA IF NOT EXISTS mailbox;
REVOKE ALL ON SCHEMA mailbox FROM PUBLIC;
SET search_path TO mailbox, public;

CREATE TABLE sync_state (
  mailbox_id text NOT NULL, stream text NOT NULL CHECK(stream IN ('live','history')),
  cursor_url text, window_start timestamptz, window_end timestamptz,
  final_end timestamptz, completed boolean NOT NULL DEFAULT false,
  lease uuid, lease_until timestamptz, retry_at timestamptz,
  pages bigint NOT NULL DEFAULT 0, last_error text, updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(mailbox_id,stream)
);
CREATE TABLE messages (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  mailbox_id text NOT NULL, canonical_key text NOT NULL,
  sender text NOT NULL, subject text NOT NULL, received_at timestamptz NOT NULL,
  modified_at timestamptz NOT NULL, content_hash text NOT NULL,
  web_link text NOT NULL DEFAULT '', deleted boolean NOT NULL DEFAULT false,
  UNIQUE(mailbox_id,canonical_key)
);
CREATE TABLE message_aliases (
  mailbox_id text NOT NULL, provider_id text NOT NULL,
  message_id bigint NOT NULL REFERENCES messages ON DELETE CASCADE,
  PRIMARY KEY(mailbox_id,provider_id)
);
CREATE TABLE source_versions (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id bigint NOT NULL REFERENCES messages ON DELETE CASCADE,
  content_hash text NOT NULL, source text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','done','failed')),
  lease uuid, lease_until timestamptz, attempts integer NOT NULL DEFAULT 0,
  retry_at timestamptz, error_code text, model text, processed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(message_id,content_hash)
);
CREATE TABLE facts (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  version_id bigint NOT NULL REFERENCES source_versions ON DELETE CASCADE,
  category text NOT NULL CHECK(category IN ('transaction','payment_method','contact')),
  fingerprint text NOT NULL, transaction_key text, vendor_domain text NOT NULL,
  payload jsonb NOT NULL, quote text NOT NULL,
  UNIQUE(version_id,category,fingerprint)
);
CREATE INDEX facts_transaction_key ON facts(transaction_key);
CREATE INDEX jobs_ready ON source_versions(status,retry_at,lease_until);
CREATE TABLE reviews (
  transaction_key text PRIMARY KEY, status text NOT NULL CHECK(status IN ('open','paid','dismissed')),
  note text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE audit_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event text NOT NULL, details jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now()
);

CREATE VIEW current_facts AS
SELECT f.*, m.mailbox_id, m.canonical_key, m.sender, m.received_at, m.web_link, m.subject
FROM facts f JOIN source_versions v ON v.id=f.version_id
JOIN messages m ON m.id=v.message_id
WHERE NOT m.deleted AND m.content_hash=v.content_hash AND v.status='done';

-- Analytics views intentionally omit full message bodies and raw quotes.
CREATE VIEW transaction_candidates AS
SELECT DISTINCT ON (transaction_key)
  transaction_key, mailbox_id, vendor_domain, payload->>'vendor' AS vendor,
  payload->>'kind' AS kind, payload->>'direction' AS direction,
  payload->>'reference' AS reference, (payload->>'amount')::numeric AS amount,
  payload->>'currency' AS currency, (payload->>'due_date')::date AS due_date,
  (payload->>'confidence')::numeric AS confidence, received_at, web_link,
  COALESCE(r.status,'open') AS review_status
FROM current_facts f LEFT JOIN reviews r USING(transaction_key)
WHERE category='transaction'
ORDER BY transaction_key, received_at DESC, id DESC;

CREATE VIEW vendor_payment_methods AS
SELECT mailbox_id, vendor_domain, payload->>'vendor' AS vendor,
  payload->>'method' AS method, count(DISTINCT canonical_key) AS source_messages,
  min(received_at) AS first_seen, max(received_at) AS last_seen
FROM current_facts WHERE category='payment_method'
GROUP BY mailbox_id,vendor_domain,payload->>'vendor',payload->>'method';

CREATE VIEW finance_contacts AS
SELECT mailbox_id, payload->>'email' AS email, payload->>'name' AS name,
  payload->>'role' AS role, vendor_domain, count(DISTINCT canonical_key) AS source_messages,
  max(received_at) AS last_seen
FROM current_facts WHERE category='contact'
GROUP BY mailbox_id,payload->>'email',payload->>'name',payload->>'role',vendor_domain;

CREATE VIEW sync_health AS
SELECT mailbox_id,stream,completed,pages,last_error,updated_at,retry_at FROM sync_state;
CREATE VIEW extraction_health AS
SELECT status,count(*) AS versions FROM source_versions GROUP BY status;
