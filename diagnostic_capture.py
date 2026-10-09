"""Sanitized failure evidence. No credentials, cookies or result pages."""
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit
from runtime_log import log_dir, event
from core import site_url

DOM_JS = r'''() => {
  const clone = document.documentElement.cloneNode(true);
  clone.querySelectorAll('script,iframe,style,link,meta,base').forEach(e=>e.remove());
  clone.querySelectorAll('input,textarea,select').forEach(e=>{
    e.removeAttribute('value'); e.textContent='';
  });
  clone.querySelectorAll('*').forEach(e=>{
    Array.from(e.attributes).forEach(a=>{
      if (!['id','class','type','name','placeholder','role','aria-hidden','aria-disabled'].includes(a.name)) e.removeAttribute(a.name);
    });
  });
  return '<!doctype html>\n'+clone.outerHTML
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi,'[email redacted]')
    .replace(/(?:\+?1[ .()-]*)?(?:\d[ .()-]*){10,}/g,'[number redacted]');
}'''


def capture_failure(page, reason):
    try:
        target = log_dir() / 'failure'
        target.mkdir(parents=True, exist_ok=True)
        for name in ('page.png', 'page.html'):
            (target / name).unlink(missing_ok=True)
        allowed_reason = reason if reason in ('challenge', 'controls', 'network', 'submission') else 'unknown'
        u = urlsplit(page.url)
        safe = site_url(page.url) and (u.path == '/' or u.path.lower() == '/internalcaptcha')
        meta = {'time': datetime.now(timezone.utc).isoformat(), 'reason': allowed_reason,
                'capture': 'sanitized_home_or_challenge' if safe else 'metadata_only',
                'query_and_credentials': 'not_recorded'}
        (target / 'status.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        if safe:
            (target / 'page.html').write_text(page.evaluate(DOM_JS), encoding='utf-8')
            page.screenshot(path=str(target / 'page.png'), full_page=True,
                            mask=[page.locator('input,textarea,select')], timeout=5000)
        event('evidence_saved', 'ok')
        return target
    except Exception:
        event('diagnostic_error', 'failed')
        return None
