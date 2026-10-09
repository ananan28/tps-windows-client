"""One homepage visit only; no personal query or CAPTCHA interaction."""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from core import HOME, blocked, proxy_config
from browser import prepare_search, AccessBlocked
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
            result['phone_tab_test'] = 'not_tested'
            try:
                field = prepare_search(page, '手机号')
                assert field.is_visible() and field.is_enabled()
                assert (field.get_attribute('name') or '').lower() != 'name'
                result['phone_field'] = {'id':field.get_attribute('id'), 'type':field.get_attribute('type'), 'name':field.get_attribute('name'), 'visible':True}
                result['phone_tab_test'] = 'passed'
            except AccessBlocked:
                result['phone_tab_test'] = 'challenge_stop'
            except Exception as exc:
                result['phone_tab_test'] = 'failed'
                result['tab_error_type'] = type(exc).__name__
            result['inputs'] = page.locator('input').evaluate_all("""els => els.map(e => ({
                id:e.id,type:e.type,name:e.name,placeholder:e.placeholder,visible:!!e.getClientRects().length}))""")
            result['tab_structure'] = page.locator('body *').evaluate_all("""els => els.filter(e =>
                /^(phone|email)$/i.test((e.textContent||'').trim()) && !e.querySelector('*')).map(e => {
                  const attrs = n => n ? {tag:n.tagName,id:n.id,cls:n.className,
                    role:n.getAttribute('role'),onclick:n.getAttribute('onclick'),
                    target:n.getAttribute('data-target'),toggle:n.getAttribute('data-toggle'),
                    href:(n.getAttribute('href')||'').startsWith('#')?n.getAttribute('href'):null} : null;
                  return {self:attrs(e),parent:attrs(e.parentElement),grandparent:attrs(e.parentElement.parentElement)};
                })""")
            result['ready_state'] = page.evaluate('document.readyState')
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


