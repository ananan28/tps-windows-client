"""One homepage visit only; no personal query or CAPTCHA interaction."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from core import HOME, blocked
result = {'environment': 'GitHub Windows runner; installed Chrome; direct network',
          'personal_query': 'not_performed', 'captcha_interaction': 'none'}
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=False)
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

