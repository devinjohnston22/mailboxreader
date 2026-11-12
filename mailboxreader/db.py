import hashlib
from pathlib import Path
import psycopg
from psycopg.rows import dict_row


def connect(settings):
    return psycopg.connect(settings.database_url, row_factory=dict_row,
                           options='-c search_path=mailbox,public -c statement_timeout=30000')


def migrate(settings):
    with connect(settings) as db:
        db.execute('SELECT pg_advisory_xact_lock(747221)')
        db.execute('CREATE TABLE IF NOT EXISTS public.schema_migrations (name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())')
        for path in sorted((Path(__file__).resolve().parent.parent / 'migrations').glob('*.sql')):
            sql = path.read_text()
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            existing = db.execute('SELECT checksum FROM public.schema_migrations WHERE name=%s', (path.name,)).fetchone()
            if existing:
                if existing['checksum'] != checksum:
                    raise RuntimeError('An applied migration has changed: ' + path.name)
                continue
            db.execute(sql)
            db.execute('INSERT INTO public.schema_migrations(name,checksum) VALUES (%s,%s)', (path.name,checksum))


if __name__ == '__main__':
    from .config import Settings
    migrate(Settings.from_env())
