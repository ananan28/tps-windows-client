"""All browser calls stay on one worker thread; GUI receives queue events."""
import queue
import threading
import re
from core import HOME, blocked, extract, site_url


def check_access(page):
    text = page.locator('body').inner_text(timeout=3000)
    if 'rate limited' in text.lower():
        raise ValueError('网站明确提示当前 IP 被限流；查询已被拒绝，不代表没有结果。请停止重试，等待网站解除限制或联系网站。')
    if blocked(text, page.url):
        raise ValueError('网站要求人工验证或限制访问；请在浏览器处理后再查询')


def first_visible(locator):
    for i in range(locator.count()):
        if locator.nth(i).is_visible():
            return locator.nth(i)
    return None


def submit_search(page, kind, value):
    if not site_url(page.url):
        raise ValueError('请先返回官网首页')
    check_access(page)
    phone = kind == '手机号'
    label = 'Phone' if phone else 'Email'
    prefix = 'Phone' if phone else 'Email'
    tab = first_visible(page.locator(f'#searchType{prefix}-d, #searchType{prefix}-m'))
    if tab is None:
        tab = first_visible(page.get_by_text(re.compile(r'^' + label + r'$', re.I)))
    if tab is not None:
        tab.click()
    selectors = ('#id-d-ph, #id-m-ph, input[type="tel"], input[name*="phone" i]' if phone
                 else '#id-d-email, #id-m-email, input[type="email"], input[name*="email" i]')
    field = None
    for _ in range(20):
        field = first_visible(page.locator(selectors))
        if field is not None: break
        page.wait_for_timeout(100)
    if field is None:
        raise ValueError('未找到可见的查询输入框；网页结构可能变化，请在浏览器手动查询')
    field.fill(value)
    form = field.locator('xpath=ancestor::form[1]')
    submit = first_visible(page.locator('#btnSubmit-d-ph, #btnSubmit-m-ph' if phone else '#btnSubmit-d-email, #btnSubmit-m-email'))
    if submit is None:
        submit = first_visible(form.locator('button[type="submit"], input[type="submit"]'))
    before = page.url
    if submit is not None: submit.click()
    else: field.press('Enter')
    for _ in range(40):
        page.wait_for_timeout(250)
        check_access(page)
        if page.url != before:
            return
    raise ValueError('提交后网址没有变化；请检查浏览器提示或手动提交。软件未确认查询成功。')


def error_message(exc, stage):
    """Show useful categories without exposing credentials from exception text."""
    text = str(exc).lower()
    if 'executable doesn' in text or 'enoent' in text or 'winerror 2' in text:
        reason = '浏览器组件缺失：请解压整个下载包，保留 _internal 文件夹'
    elif 'err_invalid_auth_credentials' in text or '407' in text:
        reason = 'HTTP 代理认证失败：请检查账号和密码'
    elif 'err_proxy_connection_failed' in text or 'err_tunnel_connection_failed' in text:
        reason = 'HTTP 代理连接失败：检查地址、端口及服务是否可用'
    elif 'timeout' in text:
        reason = '连接超时：请检查代理网络，或在浏览器点击刷新'
    elif 'err_name_not_resolved' in text:
        reason = '域名解析失败：请检查网络和代理'
    elif 'targetclosed' in type(exc).__name__.lower() or 'target closed' in text:
        reason = '浏览器已关闭或被系统阻止'
    else:
        reason = '操作失败，请检查完整解压、系统防护和代理连接'
    return f'{stage}：{reason}（{type(exc).__name__}）'

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
        failed = False
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
                    # Keep the window alive even when the proxy/homepage request fails.
                    self.emit('ready', '浏览器已启动，正在访问网站…')
                    try:
                        page.goto(HOME, wait_until='domcontentloaded')
                        self.emit('status', '浏览器已打开。验证请人工完成，然后查询。')
                    except Exception as exc:
                        self.emit('warning', error_message(exc, '网站加载失败'))
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
                                self.emit('status', '正在切换查询标签并提交…')
                                submit_search(page, *data)
                                self.emit('status', '已提交查询，请选择匹配的详情；遇验证请人工完成')
                            elif command == 'collect':
                                row = extract(page.evaluate(SNAPSHOT_JS))
                                row['query'] = data
                                self.emit('row', row)
                                self.emit('status', '当前详情已保存到本机缓存，可导出 Excel')
                        except ValueError as exc:
                            self.emit('warning', str(exc))
                        except Exception as exc:
                            self.emit('warning', error_message(exc, '浏览器操作失败'))
                        finally:
                            self.emit('idle', '')
                finally:
                    browser.close()
        except Exception as exc:
            failed = True
            self.emit('error', error_message(exc, '浏览器启动失败'))
        finally:
            self.emit('closed', '' if failed else '浏览器已停止；已采集结果仍可导出')
