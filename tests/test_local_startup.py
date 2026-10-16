"""Local launcher recovery checks; no external services or real records."""
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import local_run


class LocalStartupTest(unittest.TestCase):
    def test_busy_explicit_port_is_actionable_and_does_not_close_other_listener(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            with self.assertRaisesRegex(ValueError,'busy'):local_run.select_port(port)
            self.assertEqual(listener.getsockname()[1],port)

    def test_default_port_selects_safe_alternative_on_collision(self):
        with patch('local_run.socket.socket') as factory:
            probe=factory.return_value.__enter__.return_value
            probe.bind.side_effect=[OSError('occupied'),None]
            self.assertEqual(local_run.select_port(),5050)
            self.assertEqual(probe.bind.call_args.args[0],('127.0.0.1',5050))

    def test_metadata_cannot_open_external_or_malformed_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp,patch('urllib.request.urlopen') as network:
            home=Path(tmp)
            for url in ('https://attacker.example/business','http://localhost:5000/business','http://127.0.0.1:5000/business?redirect=evil','http://127.0.0.1:99999/business'):
                (home/'launcher.json').write_text(json.dumps(dict(url=url)))
                self.assertIsNone(local_run.existing_dashboard(home))
            self.assertFalse(network.called)

    def test_existing_dashboard_requires_actual_local_health_response(self):
        with tempfile.TemporaryDirectory() as tmp,patch('urllib.request.urlopen') as network:
            home=Path(tmp);url='http://127.0.0.1:5050/business'
            (home/'launcher.json').write_text(json.dumps(dict(url=url)))
            response=network.return_value.__enter__.return_value;response.status=200;response.read.return_value=b'{"status":"alive"}'
            self.assertEqual(local_run.existing_dashboard(home),url)
            response.read.return_value=b'{"status":"not-agencyos"}'
            self.assertIsNone(local_run.existing_dashboard(home))


import test_agencyos as fixtures
import app as application


class LocalDashboardRoutesTest(unittest.TestCase):
    setUp=fixtures.AgencyOSTest.setUp
    tearDown=fixtures.AgencyOSTest.tearDown
    post=fixtures.AgencyOSTest.post

    def test_owner_dashboard_urls_accept_optional_trailing_slash(self):
        for path in ('/launch','/launch/','/business','/business/','/gmail','/gmail/'):
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,200)

    def test_unknown_routes_still_report_not_found(self):
        self.assertEqual(self.client.get('/launch/not-a-real-page').status_code,404)


if __name__=='__main__':unittest.main()
