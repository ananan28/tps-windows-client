"""One homepage visit only; no personal query or CAPTCHA interaction."""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from core import HOME, blocked, proxy_config
raw = os.environ.get('TPS_HTTP_PROXY', '').strip()
if not raw:
    print('Proxy secret TPS_HTTP_PROXY is missing; no live request made')
    sys.exit(1)
try:
    proxy = proxy_config(raw)
except Exception:
    print('Proxy secret format invalid; no live request made')
    sys.exit(1)
result = {'environment': 'GitHub Windows runner; installed Chrome; configured HTTP proxy',
          'personal_query': 'not_performed', 'captcha_interaction': 'none'}
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=False, proxy=proxy)
    try:
        page = browser.new_page()
        page.set_default_navigation_timeout(20000)
        response = page.goto(HOME, wait_until='domcontentloaded')
        result['http_status'] = response.status if response else None
        result['path'] = urlsplit(page.url).path
        text = page.locator('body').inner_text(timeout=5000)
        result['blocked'] = blocked(text, page.url)
        result['state'] = 'blocked_stop' if result['blocked'] or result['http_status'] in (403,429) else 'homepage_loaded'
        if result['state'] == 'homepage_loaded':
            import re
            page.wait_for_load_state('load', timeout=10000)
            result['phone_tab_test'] = 'not_found'
            candidates = page.get_by_text(re.compile(r'^\s*Phone\s*$', re.I))
            for i in range(candidates.count()):
                candidate = candidates.nth(i)
                if candidate.is_visible():
                    candidate.click()
                    try:
                        page.locator('#id-d-ph').wait_for(state='visible', timeout=5000)
                        result['phone_tab_test'] = 'passed'
                    except Exception:
                        result['phone_tab_test'] = 'clicked_but_field_hidden'
                    break
            result['short_phone_elements'] = page.locator('body *').evaluate_all("""els => els.filter(e => (e.textContent||'').includes('Phone') && (e.textContent||'').trim().length < 24 && e.getClientRects().length).map(e=>({tag:e.tagName,id:e.id,text:e.textContent.trim(),onclick:e.getAttribute('onclick')})).slice(0,20)""")
            result['inputs'] = page.locator('input').evaluate_all("""els => els.map(e => ({
                id:e.id,type:e.type,name:e.name,placeholder:e.placeholder,visible:!!e.getClientRects().length}))""")
            result['tabs'] = page.locator('label,a,button,[role="tab"]').evaluate_all("""els => els.filter(e =>
                /^(phone|email)$/i.test((e.textContent||'').trim())).map(e => ({
                tag:e.tagName,id:e.id,for:e.getAttribute('for'),role:e.getAttribute('role'),visible:!!e.getClientRects().length}))""")
    except Exception as exc:
        result['state'] = 'access_error'
        result['error_type'] = type(exc).__name__
    finally:
        browser.close()
Path('live-access-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print('LIVE_ACCESS_RESULT=' + json.dumps(result, ensure_ascii=False))
