"""All browser calls stay on one worker thread; GUI receives queue events."""
import queue
import threading
from core import HOME, blocked, extract, site_url

SNAPSHOT_JS = r'''() => {
  const root = document.querySelector('#personDetails') || document.querySelector('[itemtype$="/Person"]');
  const txt = el => el ? el.innerText.trim() : '';
  const scope = root || document;
  const links = Array.from(scope.querySelectorAll('a[href]'));
  const prop = p => Array.from(scope.querySelectorAll('[itemprop="'+p+'"]')).map(e => e.content || txt(e));
  return {url: location.href, title: document.title, text: document.body.innerText,
    is_detail: !!root,
    name: txt(scope.querySelector('h1')) || prop('name')[0] || '',
    age: (txt(root).match(/Age\s+\d+(?:,\s*Born[^\n]+)?/i) || [''])[0],
    addresses: prop('address'),
    phones: links.filter(a => a.getAttribute('href').startsWith('tel:')).map(a => a.getAttribute('href').slice(4)),
    emails: links.filter(a => a.getAttribute('href').startsWith('mailto:')).map(a => a.getAttribute('href').slice(7).split('?')[0]),
    jsonld: Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(e => e.textContent)};
}'''


class BrowserWorker(threading.Thread):
    def __init__(self, proxy, events):
        super().__init__(daemon=True)
        self.proxy = proxy
        self.events = events
        self.commands = queue.Queue()
        self.stop_event = threading.Event()

    def emit(self, kind, value):
        self.events.put((kind, value))

    def run(self):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                options = {'headless': False}
                if self.proxy: options['proxy'] = self.proxy
                browser = p.chromium.launch(**options)
                try:
                    context = browser.new_context(accept_downloads=False)
                    page = context.new_page()
                    page.set_default_timeout(7000)
                    page.set_default_navigation_timeout(15000)
                    context.on('page', lambda popup: popup.close())
                    page.on('dialog', lambda d: d.dismiss())
                    page.goto(HOME, wait_until='domcontentloaded')
                    self.emit('ready', '浏览器已打开。验证请人工完成，然后查询。')
                    while not self.stop_event.is_set() and not page.is_closed():
                        try: command, data = self.commands.get_nowait()
                        except queue.Empty:
                            page.wait_for_timeout(150)
                            continue
                        try:
                            if command == 'home':
                                page.goto(HOME, wait_until='domcontentloaded')
                                self.emit('status', '已返回首页')
                            elif command == 'search':
                                kind, value = data
                                if not site_url(page.url):
                                    raise ValueError('请先返回官网首页')
                                text = page.locator('body').inner_text(timeout=3000)
                                if blocked(text, page.url):
                                    raise ValueError('请先在浏览器人工完成验证，然后重试查询')
                                # Standard form field names; no CAPTCHA interaction or stealth patches.
                                input_sel = 'input[type="email"], input[name*="email" i]' if kind == '邮箱' else 'input[type="tel"], input[name*="phone" i]'
                                candidates = page.locator(input_sel)
                                field = None
                                for i in range(candidates.count()):
                                    if candidates.nth(i).is_visible():
                                        field = candidates.nth(i); break
                                if field is None:
                                    raise ValueError('请在浏览器选择对应 Phone/Email 搜索标签，再点查询；也可手动查询')
                                field.fill(value)
                                form = field.locator('xpath=ancestor::form[1]')
                                submit = form.locator('button[type="submit"], input[type="submit"]')
                                if submit.count() and submit.first.is_visible(): submit.first.click()
                                else: field.press('Enter')
                                self.emit('status', '已提交查询，请选择匹配的详情；遇验证请人工完成')
                            elif command == 'collect':
                                row = extract(page.evaluate(SNAPSHOT_JS))
                                row['query'] = data
                                self.emit('row', row)
                                self.emit('status', '当前详情已保存到本机缓存，可导出 Excel')
                        except ValueError as exc:
                            self.emit('status', str(exc))
                        except Exception:
                            self.emit('status', '浏览器操作失败或超时；请检查页面和网络，再重试。未保存空结果。')
                        finally:
                            self.emit('idle', '')
                finally:
                    browser.close()
        except Exception:
            # Exception strings may contain proxy credentials; never put them in logs.
            self.emit('status', '浏览器启动或连接失败：检查 HTTP 代理、网络及浏览器组件。')
        finally:
            self.emit('closed', '浏览器已停止；已采集结果仍可导出')
