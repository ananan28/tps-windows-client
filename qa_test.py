"""Standard, isolated Playwright integration test. No stealth or CAPTCHA solving."""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from core import proxy_config, blocked
from diagnostic_capture import DOM_JS

FIXTURE = '''<!doctype html><html><body>
<button id="searchTypePhone-d" disabled>Phone</button>
<form id="phone-form" style="display:none" action="/submitted">
<input id="id-d-ph" type="tel" name="PhoneNo"><button type="submit">Search</button>
</form><script>
setTimeout(()=>{
 const tab=document.querySelector('#searchTypePhone-d');
 tab.addEventListener('click',()=>setTimeout(()=>{
   document.querySelector('#phone-form').style.display='block';
 },500));
 tab.disabled=false;
},1000);
</script></body></html>'''


class VerificationRequired(RuntimeError):
    pass


def check_verification(page):
    text = page.locator('body').inner_text(timeout=3000).lower()
    if blocked(text, page.url) or any(s in text for s in (
            'just a moment', 'checking your browser', 'automatic submission failed', 'verification failed')):
        raise VerificationRequired('verification_required')


def evidence(page, dest, stage, error_type):
    """Full-page screenshot with inputs masked; sanitized DOM, no exception text."""
    dest.mkdir(parents=True, exist_ok=True)
    record = {'time':datetime.now(timezone.utc).isoformat(), 'stage':stage,
              'error_type':error_type, 'screenshot':'not_saved', 'dom':'not_saved'}
    try:
        page.screenshot(path=str(dest/'failure.png'), full_page=True,
                        mask=[page.locator('input,textarea,select')], timeout=5000)
        record['screenshot']='saved'
    except Exception: pass
    try:
        (dest/'failure.html').write_text(page.evaluate(DOM_JS), encoding='utf-8')
        record['dom']='saved_sanitized'
    except Exception: pass
    (dest/'failure.json').write_text(json.dumps(record, indent=2), encoding='utf-8')


def run(args):
    dest=Path(args.output)
    dest.mkdir(parents=True, exist_ok=True)
    # The secret is read from the environment, never printed or saved.
    proxy=proxy_config(os.environ.get('TPS_HTTP_PROXY', ''))
    stage='browser_start'
    page=None
    with sync_playwright() as p:
        options={'headless':args.headless}
        if args.browser=='chrome': options['channel']='chrome'
        if proxy: options['proxy']=proxy
        browser=p.chromium.launch(**options)
        try:
            context=browser.new_context(viewport={'width':1280,'height':900},
                                        accept_downloads=False, java_script_enabled=True)
            page=context.new_page()
            page.set_default_timeout(args.timeout)
            page.set_default_navigation_timeout(args.timeout)
            if args.self_test:
                page.route('https://qa.test/**', lambda r:r.fulfill(content_type='text/html',
                    body=FIXTURE if r.request.url.endswith('/') else '<h1 id="success">Submitted</h1>'))
            stage='navigation'
            response=page.goto('https://qa.test/' if args.self_test else args.url,
                               wait_until='domcontentloaded')
            if response and response.status in (403,429): raise VerificationRequired('access_denied')
            check_verification(page)
            # A shared deadline prevents a chain of separate 20-second waits.
            deadline=time.monotonic()+args.timeout/1000
            def remaining():
                millis=int((deadline-time.monotonic())*1000)
                if millis<=0: raise TimeoutError('controls_deadline')
                return millis
            if args.ready_selector:
                stage='application_ready'
                expect(page.locator(args.ready_selector)).to_be_visible(timeout=remaining())
            tab=page.locator(args.tab_selector).filter(visible=True).first
            stage='phone_tab'
            expect(tab).to_be_visible(timeout=remaining())
            expect(tab).to_be_enabled(timeout=remaining())
            tab.click(trial=True, timeout=remaining())
            check_verification(page)
            tab.click(timeout=remaining())
            stage='phone_field'
            field=page.locator(args.input_selector).filter(visible=True).first
            expect(field).to_be_visible(timeout=remaining())
            expect(field).to_be_editable(timeout=remaining())
            check_verification(page)
            field.fill(args.value, timeout=remaining())
            expect(field).to_have_value(args.value, timeout=remaining())
            if args.submit:
                stage='submit'
                button=page.locator(args.submit_selector).filter(visible=True).first
                expect(button).to_be_enabled(timeout=args.timeout)
                button.click(trial=True, timeout=args.timeout)
                check_verification(page)
                # One attempt only. A timeout after click must not resend.
                button.click(timeout=args.timeout)
                stage='result_assertion'
                expect(page.locator(args.success_selector)).to_be_visible(timeout=args.timeout)
                check_verification(page)
            result={'passed':True,'mode':'offline_fixture' if args.self_test else 'configured_page',
                    'filled':True,'submitted':args.submit,'real_captcha_solved':False}
            (dest/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result))
            return 0
        except Exception as exc:
            if page is not None:
                # Distinguish a challenge that arrived during an element wait.
                try: check_verification(page)
                except VerificationRequired: exc=VerificationRequired('verification_required')
                except Exception: pass
                evidence(page,dest,stage,type(exc).__name__)
            print(json.dumps({'passed':False,'stage':stage,'error_type':type(exc).__name__}))
            return 1
        finally:
            browser.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url')
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--headless',action='store_true')
    parser.add_argument('--browser',choices=['chrome','chromium'],default='chrome')
    parser.add_argument('--timeout',type=int,default=20000)
    parser.add_argument('--tab-selector',default='#searchTypePhone-d')
    parser.add_argument('--input-selector',default='#id-d-ph')
    parser.add_argument('--ready-selector',help='Optional app-owned initialization signal')
    parser.add_argument('--value',default='2025550123',help='Synthetic test value; do not pass personal data here')
    parser.add_argument('--submit',action='store_true')
    parser.add_argument('--submit-selector',default='button[type=submit]')
    parser.add_argument('--success-selector')
    parser.add_argument('--output',default='logs/qa')
    args=parser.parse_args()
    if not args.self_test and not args.url: parser.error('Specify --url or --self-test')
    if args.timeout<1000 or args.timeout>120000: parser.error('Timeout must be 1000..120000 ms')
    if args.self_test: args.success_selector='#success'
    if args.submit and not args.success_selector: parser.error('--submit requires --success-selector')
    try: return run(args)
    except Exception as exc:
        print(json.dumps({'passed':False,'stage':'initialization','error_type':type(exc).__name__}))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
