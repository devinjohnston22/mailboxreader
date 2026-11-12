SET search_path TO mailbox, public;
CREATE TABLE monitor_settings (
  mailbox_id text PRIMARY KEY, threshold numeric(20,4) NOT NULL CHECK(threshold>0),
  currency text NOT NULL CHECK(currency ~ '^[A-Z]{3}$')
);
CREATE VIEW possible_overdue AS
SELECT t.*, (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date-t.due_date AS days_past_due,
  'Possible overdue — human review required; mailbox is not an accounts ledger'::text AS assessment,
  EXISTS(SELECT 1 FROM transaction_candidates p WHERE p.mailbox_id=t.mailbox_id
    AND p.vendor_domain=t.vendor_domain AND p.reference=t.reference AND t.reference IS NOT NULL
    AND p.currency=t.currency AND p.kind IN ('payment','credit','refund')) AS related_payment_evidence
FROM transaction_candidates t JOIN monitor_settings s USING(mailbox_id)
WHERE t.kind='invoice' AND t.direction='payable' AND t.amount>=s.threshold
  AND t.currency=s.currency AND t.due_date<(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date
  AND t.review_status='open';

-- One row per source fact: preserves corroborating messages after transaction dedup.
CREATE VIEW source_evidence AS
SELECT id AS fact_id, transaction_key, category, version_id, mailbox_id, web_link, received_at,
  regexp_replace(quote,'[0-9][0-9 -]{7,}[0-9]','[long numeric identifier redacted]','g') AS excerpt
FROM current_facts;
