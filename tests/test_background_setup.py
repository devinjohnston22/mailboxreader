import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest

from scripts.start_setup_background import active_setups,launch,SetupRunning
from scripts.website_config import save_settings


class BackgroundSetupTests(unittest.TestCase):
    def test_existing_setup_is_detected_without_exposing_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);proc=root/'proc';entry=proc/'12345';entry.mkdir(parents=True)
            (entry/'cmdline').write_bytes(b'bash\0'+str(root/'scripts/install_vps.sh').encode()+b'\0')
            self.assertEqual(active_setups(root,proc),[12345])
            with self.assertRaises(SetupRunning): launch(root,proc)
            self.assertFalse((root/'.local/setup.log').exists())

    def test_missing_login_cannot_start_an_unattended_installer(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);proc=root/'proc';proc.mkdir()
            save_settings(root/'.env.website',{'DASHBOARD_DOMAIN':'finance.acme.org','ACME_EMAIL':'owner@acme.org','DASHBOARD_HTTPS_PORT':'8443'})
            with self.assertRaises(RuntimeError): launch(root,proc)
            self.assertFalse((root/'.local/setup.log').exists())

    def test_background_process_has_independent_session_and_keeps_log(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);proc=root/'proc';proc.mkdir();local=root/'.local';local.mkdir()
            save_settings(root/'.env.website',{'DASHBOARD_DOMAIN':'finance.acme.org','ACME_EMAIL':'owner@acme.org','DASHBOARD_HTTPS_PORT':'8443'})
            (local/'requested-owner.json').write_text(json.dumps({'email':'owner@acme.org','password':'Synthetic-Private-123'}))
            (root/'scripts').mkdir()
            (root/'scripts/install_vps.sh').write_text('while [ ! -f .local/release-test ]; do sleep 0.02; done\nprintf "synthetic setup completed\\n"\n')
            child=launch(root,proc)
            try:
                self.assertEqual(os.getsid(child.pid),child.pid)
                with self.assertRaises(SetupRunning): launch(root,proc)
                (local/'release-test').touch()
                self.assertEqual(child.wait(timeout=10),0)
                self.assertEqual(json.loads((local/'setup-status.json').read_text())['exit_code'],0)
                text=(local/'setup.log').read_text()
                self.assertIn('synthetic setup completed',text)
                self.assertNotIn('Synthetic-Private-123',text)
                self.assertEqual(stat.S_IMODE((local/'setup.log').stat().st_mode),0o600)
            finally:
                (local/'release-test').touch()
                child.wait(timeout=10)
