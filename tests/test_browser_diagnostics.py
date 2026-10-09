import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from runtime_log import setup_logging, close_logging
from browser_diagnostics import attach_context_diagnostics, resource_kind


class DiagnosticsTests(unittest.TestCase):
    def tearDown(self):
        close_logging()

    def test_popup_and_dialog_remain_for_manual_interaction(self):
        handlers = {}
        ctx = SimpleNamespace(pages=[], on=lambda name, cb: handlers.update({name: cb}))
        attach_context_diagnostics(ctx)
        page_handlers = {}
        page = SimpleNamespace(close=Mock(), on=lambda name, cb: page_handlers.update({name: cb}))
        handlers['page'](page)
        page.close.assert_not_called()
        dialog = SimpleNamespace(accept=Mock(), dismiss=Mock())
        page_handlers['dialog'](dialog)
        dialog.accept.assert_not_called(); dialog.dismiss.assert_not_called()

    def test_network_and_code_diagnostics_do_not_leak_data(self):
        handlers = {}
        page = SimpleNamespace(on=lambda name, cb: handlers.update({name: cb}))
        with tempfile.TemporaryDirectory() as d:
            logger = setup_logging(d)
            attach_context_diagnostics(SimpleNamespace(pages=[page], on=lambda *args: None))
            handlers['requestfailed'](SimpleNamespace(
                url='https://challenges.cloudflare.com/script?secret_password=2025550123',
                resource_type='script', failure='net::ERR_TUNNEL_CONNECTION_FAILED secret_password'))
            handlers['console'](SimpleNamespace(text='[Cloudflare Turnstile] Error: 600010 private@example.test'))
            handlers['response'](SimpleNamespace(url='https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/pat/token', status=401))
            handlers['requestfailed'](SimpleNamespace(url='https://test.challenges.cloudflare.com/', resource_type='script', failure='DNS'))
            text = (Path(d) / 'runtime.log').read_text()
            for value in ('secret_password', '2025550123', 'private@example.test', '/pat/', 'token'):
                self.assertNotIn(value, text)
            rows = [json.loads(line) for line in text.splitlines()]
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[1]['outcome'], 'proxy_connection')
            self.assertEqual(rows[2]['error_code'], 600010)
            for h in logger.handlers: h.close()

    def test_host_boundary(self):
        self.assertIsNone(resource_kind('https://challenges.cloudflare.com.evil.test/path'))
        self.assertIsNone(resource_kind('https://random.challenges.cloudflare.com/path'))
        self.assertEqual(resource_kind('https://challenges.cloudflare.com/script'), 'cloudflare')


if __name__ == '__main__': unittest.main()
