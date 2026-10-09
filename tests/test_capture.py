import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from diagnostic_capture import capture_failure


class CaptureTests(unittest.TestCase):
    def test_results_are_never_captured_and_old_evidence_removed(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'failure'; target.mkdir()
            (target/'page.png').write_bytes(b'old')
            (target/'page.html').write_text('old')
            page=Mock(); page.url='https://www.truepeoplesearch.com/results?PhoneNo=2025550123'
            with patch('diagnostic_capture.log_dir',return_value=Path(d)):
                capture_failure(page,'submission')
            page.screenshot.assert_not_called(); page.evaluate.assert_not_called()
            self.assertFalse((target/'page.png').exists())
            self.assertFalse((target/'page.html').exists())
            text=(target/'status.json').read_text()
            self.assertNotIn('2025550123',text)
            self.assertEqual(json.loads(text)['capture'],'metadata_only')

    def test_capture_errors_do_not_propagate(self):
        page=Mock(); page.url='https://www.truepeoplesearch.com/'
        page.evaluate.side_effect=RuntimeError('private')
        with tempfile.TemporaryDirectory() as d, patch('diagnostic_capture.log_dir',return_value=Path(d)):
            self.assertIsNone(capture_failure(page,'controls'))


if __name__=='__main__': unittest.main()
