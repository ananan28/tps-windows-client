import tempfile
import unittest
from pathlib import Path
from core import proxy_config, query_value, extract, export_xlsx, site_url


class CoreTests(unittest.TestCase):
    def test_authenticated_http_and_colons_in_password(self):
        p = proxy_config('example.test:8080:user:pass:word')
        self.assertEqual(p['server'], 'http://example.test:8080')
        self.assertEqual(p['password'], 'pass:word')
        self.assertEqual(proxy_config('http://user:p%40ss@example.test:8080')['password'], 'p@ss')

    def test_bad_proxy_rejected(self):
        for value in ['host:0:u:p', 'host:99999', 'socks5://host:8080', 'host:8080:u:']:
            with self.assertRaises(ValueError): proxy_config(value)

    def test_inputs_and_host_boundary(self):
        self.assertEqual(query_value('手机号', '+1 (202) 555-0123'), '2025550123')
        with self.assertRaises(ValueError): query_value('手机号','12')
        self.assertFalse(site_url('https://www.truepeoplesearch.com.evil.test/a'))

    def test_challenge_never_becomes_result(self):
        with self.assertRaises(ValueError): extract({'url':'https://www.truepeoplesearch.com/InternalCaptcha', 'is_detail':True,'name':'Test'})
        with self.assertRaises(ValueError): extract({'url':'https://www.truepeoplesearch.com/results', 'is_detail':False,'name':'Test'})

    def test_jsonld_and_dedup(self):
        row = extract({'url':'https://www.truepeoplesearch.com/details/test', 'is_detail':True,
            'jsonld':['{"@graph":[{"@type":"Person","name":"Test Person","telephone":"2025550123","address":{"streetAddress":"Example St","addressLocality":"Test City"}}]}'],
            'phones':['2025550123']})
        self.assertEqual(row['phones'],'2025550123')
        self.assertEqual(row['addresses'],'Example St, Test City')

    def test_excel_text_is_not_formula(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'test.xlsx'
            export_xlsx([{'name':'=HYPERLINK("bad")','phones':'+12025550123'}],path)
            book = load_workbook(path)
            self.assertEqual(book.active['B2'].data_type,'s')
            self.assertEqual(book.active['E2'].value,'+12025550123')


if __name__ == '__main__': unittest.main()
