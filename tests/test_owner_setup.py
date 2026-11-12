import json
from pathlib import Path
import stat
import tempfile
import unittest
from scripts.bootstrap_metabase import initial_credentials


class InitialOwnerTests(unittest.TestCase):
    def test_private_chosen_login_is_used_and_retry_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            access=Path(folder)/'admin.json';requested=Path(folder)/'requested.json'
            chosen={'email':'owner@example.invalid','password':'Synthetic-Strong-123'}
            requested.write_text(json.dumps(chosen))
            self.assertEqual(initial_credentials(access,requested),chosen)
            self.assertEqual(stat.S_IMODE(access.stat().st_mode),0o600)
            self.assertEqual(initial_credentials(access,requested),chosen)

    def test_existing_owner_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            access=Path(folder)/'admin.json';requested=Path(folder)/'requested.json'
            access.write_text(json.dumps({'email':'existing@example.invalid','password':'Synthetic-Existing-123'}))
            before=access.read_bytes()
            with self.assertRaises(RuntimeError): initial_credentials(access,requested)
            self.assertEqual(access.read_bytes(),before)

    def test_invalid_requested_login_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            access=Path(folder)/'admin.json';requested=Path(folder)/'requested.json'
            requested.write_text(json.dumps({'email':'not-an-email','password':'short'}))
            with self.assertRaises(ValueError): initial_credentials(access,requested)
            self.assertFalse(access.exists())
