import json
import tempfile
import unittest
from pathlib import Path
from runtime_log import event, setup_logging


class RuntimeLogTests(unittest.TestCase):
    def test_only_safe_fields_are_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            logger = setup_logging(d)
            event('browser_start', 'proxy')
            event('homepage_load', 'ok', http_status=403)
            event('access_pause', 'challenge', submitted=False)
            event('2025550123 secret_user:secret_password')
            event('operation_error', 'secret_password')
            event('input_fill', 'ok', count='private@example.test', submitted='secret')
            text = (Path(d) / 'runtime.log').read_text(encoding='utf-8')
            for secret in ('2025550123', 'secret_user', 'secret_password', 'private@example.test'):
                self.assertNotIn(secret, text)
            rows = [json.loads(line) for line in text.splitlines()]
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[1]['http_status'], 403)
            self.assertIs(rows[2]['submitted'], False)
            self.assertNotIn('count', rows[3])
            for h in logger.handlers: h.close()

    def test_rotation_retains_bounded_valid_logs(self):
        with tempfile.TemporaryDirectory() as d:
            logger = setup_logging(d, max_bytes=500, backups=2)
            for _ in range(80): event('command_start', 'search')
            paths = list(Path(d).glob('runtime.log*'))
            self.assertEqual(len(paths), 3)
            for p in paths:
                self.assertLessEqual(p.stat().st_size, 500)
                for line in p.read_text().splitlines(): json.loads(line)
            for h in logger.handlers: h.close()

    def test_unwritable_destination_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            occupied = Path(d) / 'file'; occupied.write_text('occupied')
            setup_logging(occupied)
            event('browser_start', 'proxy')


if __name__ == '__main__': unittest.main()
