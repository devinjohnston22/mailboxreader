import unittest
import httpx
from scripts.website_config import validate
from scripts.verify_website import verify


class WebsiteTests(unittest.TestCase):
    def test_reject_placeholder_or_injected_hostnames(self):
        for domain in ['example.com','finance.example.com','finance.your-domain.com','localhost',
                       'https://finance.acme.org','finance.acme.org/path','finance.acme.org:443',
                       'finance.acme.org\nrespond secret','finance.acme.org{','*.acme.org']:
            with self.subTest(domain=domain):
                with self.assertRaises(ValueError): validate({'DASHBOARD_DOMAIN':domain,'ACME_EMAIL':'admin@acme.org'})

    def test_accept_real_hostname_shape(self):
        self.assertEqual(validate({'DASHBOARD_DOMAIN':'finance.acme.org','ACME_EMAIL':'admin@acme.org'})['DASHBOARD_DOMAIN'],'finance.acme.org')

    def test_https_gui_verification_detects_broken_upstream(self):
        def healthy(request):
            if request.url.path=='/api/health': return httpx.Response(200,json={'status':'ok'})
            return httpx.Response(200,text='<html>Dashboard</html>',headers={'Content-Type':'text/html','Strict-Transport-Security':'max-age=31536000'})
        settings={'DASHBOARD_DOMAIN':'finance.acme.org'}
        with httpx.Client(transport=httpx.MockTransport(healthy)) as client:
            self.assertEqual(verify(settings,client),'https://finance.acme.org')
        with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(503))) as client:
            with self.assertRaises(httpx.HTTPStatusError): verify(settings,client)

    def test_https_gui_verification_requires_security_headers(self):
        def missing(request):
            if request.url.path=='/api/health': return httpx.Response(200,json={'status':'ok'})
            return httpx.Response(200,text='<html>Dashboard</html>',headers={'Content-Type':'text/html'})
        with httpx.Client(transport=httpx.MockTransport(missing)) as client:
            with self.assertRaises(RuntimeError): verify({'DASHBOARD_DOMAIN':'finance.acme.org'},client)
