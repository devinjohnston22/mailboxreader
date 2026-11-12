"""Run with the application-owner DSN; never give this DSN to Metabase."""
import os
import psycopg
from psycopg import sql

VIEWS = ['transaction_candidates','vendor_payment_methods','finance_contacts',
         'sync_health','extraction_health','possible_overdue','source_evidence']


def provision(db,password):
    if len(password)<32:
        raise ValueError('ANALYTICS_PASSWORD must contain at least 32 characters')
    if not db.execute("SELECT 1 FROM pg_roles WHERE rolname='mailbox_analytics'").fetchone():
        db.execute('CREATE ROLE mailbox_analytics LOGIN')
    # psycopg SQL literal quoting; no shell interpolation or statement logging.
    db.execute(sql.SQL('ALTER ROLE mailbox_analytics WITH PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION').format(sql.Literal(password)))
    db.execute('ALTER ROLE mailbox_analytics SET default_transaction_read_only=on')
    db.execute('REVOKE ALL ON SCHEMA public FROM mailbox_analytics')
    db.execute('GRANT USAGE ON SCHEMA mailbox TO mailbox_analytics')
    db.execute('REVOKE ALL ON ALL TABLES IN SCHEMA mailbox FROM mailbox_analytics')
    for view in VIEWS:
        db.execute(sql.SQL('GRANT SELECT ON mailbox.{} TO mailbox_analytics').format(sql.Identifier(view)))


if __name__=='__main__':
    with psycopg.connect(os.environ['DATABASE_URL']) as db:
        provision(db,os.environ['ANALYTICS_PASSWORD'])
    print('Analytics role configured; raw sources and writes are not granted.')
