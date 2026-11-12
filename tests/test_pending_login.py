import errno
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock

from scripts.reenter_dashboard_login import check_uninitialized,write_pending
from scripts.website_config import read_settings,save_settings


class PendingLoginTests(unittest.TestCase):
    def test_reentry_preserves_site_and_private_backups(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.local').mkdir()
            settings={'DASHBOARD_DOMAIN':'finance.acme.org','ACME_EMAIL':'old@acme.org','DASHBOARD_HTTPS_PORT':'8443'}
            save_settings(root/'.env.website',settings)
            old={'email':'old@acme.org','password':'Synthetic-Old-123'}
            (root/'.local/requested-owner.json').write_text(json.dumps(old))
            backup=write_pending(root,'new@acme.org','Synthetic-New-123')
            current=read_settings(root/'.env.website')
            self.assertEqual(current['DASHBOARD_DOMAIN'],'finance.acme.org')
            self.assertEqual(current['DASHBOARD_HTTPS_PORT'],'8443')
            self.assertEqual(current['ACME_EMAIL'],'new@acme.org')
            self.assertEqual(json.loads((backup/'requested-owner.json').read_text()),old)
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode),0o700)
            self.assertEqual(stat.S_IMODE((backup/'requested-owner.json').stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE((root/'.local/requested-owner.json').stat().st_mode),0o600)
            self.assertFalse((root/'.local/metabase-admin.json').exists())

    def test_existing_login_and_invalid_input_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.local').mkdir()
            saved=root/'.local/metabase-admin.json';saved.write_text('existing account metadata')
            before=saved.read_bytes()
            with self.assertRaises(RuntimeError): write_pending(root,'owner@acme.org','Synthetic-New-123')
            self.assertEqual(saved.read_bytes(),before)
            saved.unlink()
            with self.assertRaises(ValueError): write_pending(root,'owner@acme.org','short')
            self.assertFalse((root/'.env.website').exists())

    def test_server_state_is_checked_without_resetting_any_account(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            opener=Mock()
            opener.open.return_value=io.BytesIO(b'{"setup-token":null}')
            with self.assertRaises(RuntimeError): check_uninitialized(root,opener)
            opener.open.return_value=io.BytesIO(b'{"setup-token":"synthetic-first-run-token"}')
            check_uninitialized(root,opener)
            opener.open.side_effect=urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED,'Connection refused'))
            check_uninitialized(root,opener)
            opener.open.side_effect=urllib.error.URLError(TimeoutError('timed out'))
            with self.assertRaises(RuntimeError): check_uninitialized(root,opener)
