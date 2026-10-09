"""All browser calls stay on one worker thread; GUI receives queue events."""
import queue
import threading
import re
import os
import hashlib
from pathlib import Path
from core import HOME, blocked, extract, site_url


def profile_dir(proxy, channel):
    identity = (proxy or {}).get('server', 'direct') + '|' + (proxy or {}).get('username', '')
    key = hashlib.sha256(identity.encode()).hexdigest()[:16]
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TPSWindowsClient'
    return base / 'browser-profiles' / channel / key


def open_context(playwright, proxy, channel, directory, headless=False):
    options = {'headless': headless, 'accept_downloads': False}
    if proxy:
        options['proxy'] = proxy
    options['channel'] = 'chrome'
    return playwright.chromium.launch_persistent_context(str(directory), **options)


class AccessBlocked(ValueError):
    def __init__(self, message, submitted=False):
        super().__init__(message)
        self.submitted = submitted


def check_access(page):
    text = page.locator('body').inner_text(timeout=3000)
    low = text.lower()
    if 'rate limited' in low:
        raise AccessBlocked('网站拒绝当前请求（限流），请停止重试；这不是无结果。')
    challenge = blocked(text, page.url) or any(x in low for x in (
        'just a moment', 'checking your browser', 'automatic submission failed',
        'verification failed', '验证失败'))
    if challenge:
        raise AccessBlocked('网站验证尚未完成，查询已暂停；人工完成后点“继续查询”。')


def first_visible(locator):
    for i in range(locator.count()):
        item = locator.nth(i)
        if item.is_visible():
            return item
    return None


def wait_visible(page, locator, timeout=15000):
    import time
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        check_access(page)
        item = first_visible(locator)
        if item is not None and item.is_enabled():
            return item
        page.wait_for_timeout(150)
    check_access(page)
    raise ValueError('等待查询控件就绪超时；查询未提交。可能是脚本未加载或网页结构改变。')


def prepare_search(page, kind):
    if not site_url(page.url):
        raise ValueError('请先返回官网首页')
    check_access(page)
    phone = kind == '手机号'
    label = 'Phone' if phone else 'Email'
    pattern = re.compile(r'^\s*' + label + r'\s*$', re.I)
    tabs = page.locator(f'#searchType{label}-d, #searchType{label}-m').or_(
        page.locator('label, a, button, [role="tab"]').filter(has_text=pattern)).or_(
        page.get_by_text(pattern))
    tab = wait_visible(page, tabs)
    tab.click()
    selectors = ('#id-d-ph, #id-m-ph, input[type="tel"], input[name*="phone" i], input[name="ph"], input[placeholder*="phone" i]' if phone
                 else '#id-d-em, #id-d-email, #id-m-email, input[type="email"], input[name*="email" i]')
    field = wait_visible(page, page.locator(selectors))
    return field


def submit_search(page, kind, value):
    field = prepare_search(page, kind)
    field.fill(value)
    form = field.locator('xpath=ancestor::form[1]')
    phone = kind == '手机号'
    submit = first_visible(page.locator('#btnSubmit-d-ph, #btnSubmit-m-ph' if phone else '#btnSubmit-d-email, #btnSubmit-m-email'))
    if submit is None:
        submit = first_visible(form.locator('button[type="submit"], input[type="submit"]'))
    before = page.url
    if submit is not None:
        submit.click()
    else:
        field.press('Enter')
    try:
        import time
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            page.wait_for_timeout(150)
            check_access(page)
            if page.url != before:
                return
    except AccessBlocked as exc:
        exc.submitted = True
        raise
    raise ValueError('提交后未确认跳转，请检查浏览器提示；软件不会自动重复提交。')


def error_message(exc, stage):
    """Show useful categories without exposing credentials from exception text."""
    text = str(exc).lower()
    if 'executable doesn' in text or 'enoent' in text or 'winerror 2' in text:
        reason = '未找到 Google Chrome，请先安装 Chrome；轻量版不包含浏览器'
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
    def __init__(self, proxy, events, channel="chrome"):
        super().__init__(daemon=True)
        self.proxy = proxy
        self.channel = channel
        self.events = events
        self.commands = queue.Queue()
        self.stop_event = threading.Event()
        self.pending_search = None

    def emit(self, kind, value):
        self.events.put((kind, value))

    def run(self):
        failed = False
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                context = open_context(p, self.proxy, self.channel, profile_dir(self.proxy, self.channel))
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.set_default_timeout(7000)
                    page.set_default_navigation_timeout(15000)
                    context.on('page', lambda popup: popup.close())
                    page.on('dialog', lambda d: d.dismiss())
                    # Keep the window alive even when the proxy/homepage request fails.
                    self.emit('status', '浏览器已启动，正在访问网站…')
                    try:
                        page.goto(HOME, wait_until='domcontentloaded')
                        self.emit('status', '浏览器已打开。验证请人工完成，然后查询。')
                    except Exception as exc:
                        self.emit('warning', error_message(exc, '网站加载失败'))
                    self.emit('ready', '浏览器已就绪；验证未完成时查询会暂停')
                    while not self.stop_event.is_set() and not page.is_closed():
                        try: command, data = self.commands.get_nowait()
                        except queue.Empty:
                            page.wait_for_timeout(150)
                            continue
                        try:
                            if command == 'home':
                                page.goto(HOME, wait_until='domcontentloaded')
                                self.emit('status', '已返回首页')
                            elif command == 'resume':
                                if self.pending_search is None:
                                    raise ValueError('没有暂停的查询')
                                data, submitted = self.pending_search
                                check_access(page)
                                if not submitted:
                                    submit_search(page, *data)
                                self.pending_search = None
                                self.emit('status', '验证已解除；请在浏览器选择详情。未重复提交已发送的查询。')
                            elif command == 'search':
                                self.pending_search = None
                                self.emit('status', '正在切换查询标签并提交…')
                                submit_search(page, *data)
                                self.emit('status', '已提交查询，请选择匹配的详情；遇验证请人工完成')
                            elif command == 'collect':
                                row = extract(page.evaluate(SNAPSHOT_JS))
                                row['query'] = data
                                self.emit('row', row)
                                self.emit('status', '当前详情已保存到本机缓存，可导出 Excel')
                        except AccessBlocked as exc:
                            if command in ('search', 'resume'):
                                self.pending_search = (data, exc.submitted or (command == 'resume' and submitted))
                            self.emit('warning', str(exc))
                        except ValueError as exc:
                            self.emit('warning', str(exc))
                        except Exception as exc:
                            self.emit('warning', error_message(exc, '浏览器操作失败'))
                        finally:
                            self.emit('idle', '')
                finally:
                    context.close()
        except Exception as exc:
            failed = True
            self.emit('error', error_message(exc, '浏览器启动失败'))
        finally:
            self.emit('closed', '' if failed else '浏览器已停止；已采集结果仍可导出')
