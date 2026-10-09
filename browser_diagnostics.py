"""Passive diagnostics; never interact with, solve or modify a challenge."""
import re
from urllib.parse import urlsplit
from runtime_log import event


def resource_kind(url):
    u = urlsplit(url)
    if u.scheme != 'https': return None
    if u.hostname == 'challenges.cloudflare.com':
        # PAT 401 is expected on unsupported devices, not a challenge failure.
        return 'pat' if '/pat/' in u.path else 'cloudflare'
    if u.hostname in ('truepeoplesearch.com', 'www.truepeoplesearch.com'):
        return 'site'
    # Ignore Cloudflare wildcard DNS probes and unrelated third-party traffic.
    return None


def attach_diagnostics(page):
    def failed(request):
        try:
            kind = resource_kind(request.url)
            if kind not in ('cloudflare', 'site'): return
            # Site scripts/documents matter; don't log image/ad failures.
            if kind == 'site' and request.resource_type not in ('document', 'script'): return
            event('resource_failed', kind)
            low = (request.failure or '').lower()
            reason = next((code for token, code in (
                ('proxy', 'proxy_connection'), ('tunnel', 'proxy_connection'),
                ('timed_out', 'timeout'), ('name_not_resolved', 'dns'),
                ('cert_', 'tls'), ('blocked_by_client', 'extension_block'))
                if token in low), 'unknown')
            event('network_error', reason)
        except Exception:
            event('diagnostic_error', 'failed')

    def response(value):
        try:
            kind = resource_kind(value.url)
            if kind == 'pat' and value.status == 401: return
            if kind == 'cloudflare' and value.status >= 400:
                event('resource_http', kind, http_status=value.status)
            elif kind == 'site' and value.request.resource_type == 'document':
                event('document_http', kind, http_status=value.status)
        except Exception:
            event('diagnostic_error', 'failed')

    def console(message):
        try:
            text = message.text
            if 'turnstile' not in text.lower(): return
            code = re.search(r'\b(?:error|code)\s*[:=]?\s*[\x27\x22]?(\d{6})\b', text, re.I)
            if code: event('challenge_code', 'failed', error_code=int(code.group(1)))
        except Exception:
            event('diagnostic_error', 'failed')

    page.on('requestfailed', failed)
    page.on('response', response)
    page.on('console', console)
    # With a listener installed, Playwright does not auto-dismiss this dialog.
    # Leave it for the person using the visible browser; don't accept/dismiss it.
    page.on('dialog', lambda dialog: event('browser_dialog', 'manual'))


def attach_context_diagnostics(context):
    for page in context.pages: attach_diagnostics(page)
    def new_page(page):
        event('popup_open', 'manual')
        attach_diagnostics(page)
    context.on('page', new_page)
