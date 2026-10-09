import json
import os
import queue
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'

from core import VERSION, proxy_config, query_value, export_xlsx
from browser import BrowserWorker
from runtime_log import event, setup_logging, log_dir


def data_dir():
    path = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TPSWindowsClient'
    path.mkdir(parents=True, exist_ok=True)
    return path


def self_test():
    """Offline bundled browser + actual XLSX smoke test; no real people or network."""
    from playwright.sync_api import sync_playwright
    from browser import SNAPSHOT_JS, submit_search, open_context, AccessBlocked
    from core import extract
    import tempfile
    setup_logging()
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel='chrome')
        try:
            test_context = b.new_context()
            page = test_context.new_page()
            from browser_diagnostics import attach_context_diagnostics
            attach_context_diagnostics(page.context)
            popup = page.context.new_page()
            assert not popup.is_closed()
            popup.close()
            page.route('https://www.truepeoplesearch.com/**', lambda route: route.fulfill(
                content_type='text/html', body='<div id="personDetails"><h1>Test Person</h1><a href="tel:2025550123">Test</a></div>'))
            page.goto('https://www.truepeoplesearch.com/test-detail')
            row = extract(page.evaluate(SNAPSHOT_JS))
            assert row['name'] == 'Test Person'
            assert row['phones'] == '2025550123'
            fixture = '''<form action="/name-result"><input placeholder="Enter name, phone or address" name="Name"></form>
                <span id="searchTypePhone-d" class="search-type"><span> Phone </span></span>
                <form id="phone-form" style="display:none" action="/resultphone"><input type="text" placeholder="Enter phone number" name="q">
                <button type="submit">Search</button></form>
                <script>setTimeout(()=>document.querySelector('#searchTypePhone-d').addEventListener('click',()=>{
                  document.querySelector('#searchTypePhone-d').classList.add('search-type-selected');
                  setTimeout(()=>document.querySelector('#phone-form').style.display='block',800);
                }),1200);</script>'''
            page.unroute('https://www.truepeoplesearch.com/**')
            page.route('https://www.truepeoplesearch.com/**', lambda route: route.fulfill(
                content_type='text/html', body=fixture if route.request.url.endswith('/') else 'This IP has been rate limited'))
            page.goto('https://www.truepeoplesearch.com/')
            try:
                submit_search(page, '手机号', '2025550123')
                raise AssertionError('Rate limiting must be reported')
            except ValueError as exc:
                assert '限流' in str(exc)
                assert isinstance(exc, AccessBlocked) and exc.submitted
            assert 'q=2025550123' in page.url
            page.unroute('https://www.truepeoplesearch.com/**')
            page.route('https://www.truepeoplesearch.com/**', lambda route: route.fulfill(
                content_type='text/html', body='<p>Verify you are human</p>' + fixture))
            page.goto('https://www.truepeoplesearch.com/')
            try:
                submit_search(page, '手机号', '2025550123')
                raise AssertionError('Challenge must pause before typing')
            except AccessBlocked as exc:
                assert not exc.submitted
            assert page.url == 'https://www.truepeoplesearch.com/'
            page.route('https://challenges.cloudflare.com/**', lambda route: route.fulfill(
                status=503, body='Offline fixture', headers={'Access-Control-Allow-Origin': '*'}))
            page.evaluate("async () => { try { await fetch('https://challenges.cloudflare.com/offline-test'); } catch {} }")
            with tempfile.TemporaryDirectory() as d:
                dest = Path(d) / 'smoke.xlsx'
                export_xlsx([row], dest)
                assert dest.exists()
        finally: b.close()
        with tempfile.TemporaryDirectory() as profile:
            ctx = open_context(p, None, 'chrome', profile, headless=True)
            try:
                ctx.add_cookies([{'name': 'offline_test', 'value': 'retained',
                    'domain': 'example.test', 'path': '/', 'expires': 2000000000}])
            finally:
                ctx.close()
            ctx = open_context(p, None, 'chrome', profile, headless=True)
            try:
                assert any(c['name'] == 'offline_test' for c in ctx.cookies())
            finally:
                ctx.close()
    # Verify that the packaged Tcl/Tk runtime can create a window on Windows.
    import tkinter as tk
    root = tk.Tk(); root.withdraw(); root.update(); root.destroy()
    log_text = (log_dir() / 'runtime.log').read_text(encoding='utf-8')
    log_rows = [json.loads(line) for line in log_text.splitlines()]
    assert any(r['event'] == 'input_fill' for r in log_rows)
    assert any(r['event'] == 'access_pause' for r in log_rows)
    assert any(r['event'] == 'popup_open' for r in log_rows)
    assert any(r['event'] == 'resource_http' and r['http_status'] == 503 for r in log_rows)
    assert '2025550123' not in log_text and 'Test Person' not in log_text
    Path('self-test-result.json').write_text(json.dumps({
        'version': VERSION, 'offline_browser': 'passed', 'xlsx': 'passed',
        'tkinter': 'passed', 'installed_chrome_persistent_session': 'passed', 'query_tab_submit_and_rate_limit': 'passed', 'delayed_tab_listener': 'passed', 'runtime_log': 'passed', 'passive_challenge_diagnostics': 'passed', 'popup_kept_open': 'passed', 'live_site': 'not_tested'}), encoding='utf-8')


def main():
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog

    class App:
        def __init__(self, root):
            self.root = root
            self.worker = None
            self.events = queue.Queue()
            self.rows = []
            self.busy = False
            self.last_query = ''
            self.closing = False
            self.log_window = None
            self.log_text = None
            self.log_content = None
            setup_logging()
            event('app_start', 'ok')
            root.report_callback_exception = self.callback_error
            self.cache = data_dir() / 'results.json'
            self.proxy = tk.StringVar()
            self.query = tk.StringVar()
            self.kind = tk.StringVar(value='手机号')
            self.engine = tk.StringVar(value='本机 Chrome')
            self.consent = tk.BooleanVar()
            self.auto_search = tk.BooleanVar(value=True)
            self.status = tk.StringVar(value='填写 HTTP 代理 → 打开浏览器 → 查询 → 打开详情 → 采集 → 导出')
            root.title(f'TPS Windows Client {VERSION} · 测试版')
            root.geometry('1050x620'); root.minsize(820, 500)
            style = ttk.Style(); style.theme_use('clam')
            style.configure('TButton', padding=8)
            frame = ttk.Frame(root, padding=20); frame.pack(fill='both', expand=True)
            ttk.Label(frame, text='TPS Windows Client', font=('Segoe UI', 21, 'bold')).pack(anchor='w')
            ttk.Label(frame, text='单线程 · HTTP 代理 · 数据仅存本机 · 网站验证由你人工完成').pack(anchor='w', pady=(2, 15))
            ttk.Label(frame, text='HTTP 代理（留空直连；host:port:user:password；仅保存在本次内存）').pack(anchor='w')
            self.proxy_entry = ttk.Entry(frame, textvariable=self.proxy, show='•')
            self.proxy_entry.pack(fill='x', pady=5)
            tools = ttk.Frame(frame); tools.pack(fill='x')
            self.engine_select = ttk.Combobox(tools, values=['本机 Chrome'], textvariable=self.engine, state='readonly', width=15)
            self.engine_select.pack(side='right')
            self.open_button = ttk.Button(tools, text='1. 打开浏览器', command=self.start); self.open_button.pack(side='left')
            self.home_button = ttk.Button(tools, text='返回首页', command=lambda: self.send('home')); self.home_button.pack(side='left', padx=5)
            ttk.Button(tools, text='停止浏览器', command=self.stop).pack(side='left')
            self.resume_button = ttk.Button(tools, text='继续查询', command=lambda: self.send('resume'))
            self.resume_button.pack(side='left', padx=5)
            line = ttk.Frame(frame); line.pack(fill='x', pady=12)
            ttk.Combobox(line, values=['手机号', '邮箱'], textvariable=self.kind, state='readonly', width=9).pack(side='left')
            ttk.Entry(line, textvariable=self.query).pack(side='left', fill='x', expand=True, padx=8)
            self.search_button = ttk.Button(line, text='2. 查询', command=self.search); self.search_button.pack(side='left')
            self.collect_button = ttk.Button(line, text='3. 采集当前详情', command=self.collect); self.collect_button.pack(side='left', padx=5)
            ttk.Checkbutton(frame, text='我确认仅查询自己的或获得授权的测试资料', variable=self.consent).pack(anchor='w')
            ttk.Checkbutton(frame, text='打开后自动查询已填写的号码/邮箱（须先勾选授权）', variable=self.auto_search).pack(anchor='w')
            ttk.Label(frame, text='查询时自动切换 Phone/Email 标签；结果页请自己选择正确人员。').pack(anchor='w', pady=6)
            self.table = ttk.Treeview(frame, columns=('name','age','phones','emails'), show='headings')
            for key, label in [('name','姓名'),('age','年龄'),('phones','电话'),('emails','邮箱')]:
                self.table.heading(key, text=label); self.table.column(key, width=180)
            self.table.pack(fill='both', expand=True, pady=8)
            bottom = ttk.Frame(frame); bottom.pack(side='bottom', fill='x', before=self.table)
            ttk.Button(bottom, text='4. 导出 Excel', command=self.export).pack(side='left')
            ttk.Button(bottom, text='清空本机结果', command=self.clear).pack(side='left', padx=8)
            ttk.Button(bottom, text='运行日志', command=self.show_logs).pack(side='left', padx=8)
            ttk.Label(frame, textvariable=self.status, wraplength=760).pack(side='bottom', fill='x', pady=(6,0), before=self.table)
            try:
                cached = json.loads(self.cache.read_text(encoding='utf-8'))
                if isinstance(cached, list):
                    self.rows = [r for r in cached if isinstance(r, dict)]
                    for row in self.rows: self.insert(row)
            except FileNotFoundError: pass
            except (ValueError, OSError): self.status.set('旧缓存无法读取；请备份或清空后继续')
            root.protocol('WM_DELETE_WINDOW', self.close)
            self.buttons()
            root.after(100, self.poll)

        def callback_error(self, exc_type, exc, traceback):
            event('unhandled_error', 'failed')
            self.status.set('界面操作异常，请查看运行日志')
            messagebox.showerror('界面错误', '界面操作异常；已记录安全错误事件，请提供运行日志。')

        def show_logs(self):
            if self.log_window is not None and self.log_window.winfo_exists():
                self.log_window.lift(); return
            from tkinter.scrolledtext import ScrolledText
            self.log_window = tk.Toplevel(self.root)
            self.log_window.title('运行日志（自动刷新）')
            self.log_window.geometry('880x480')
            ttk.Label(self.log_window, text='UTC 时间 · 日志只记录步骤，不包含查询资料、代理账号密码或网页内容').pack(anchor='w', padx=10, pady=6)
            ttk.Label(self.log_window, text=str(log_dir()), wraplength=850).pack(anchor='w', padx=10)
            ttk.Button(self.log_window, text='打开日志文件夹', command=self.open_log_folder).pack(anchor='w', padx=10, pady=6)
            self.log_text = ScrolledText(self.log_window, wrap='none', state='disabled')
            self.log_text.pack(fill='both', expand=True, padx=10, pady=6)
            self.log_content = None
            self.refresh_logs()

        def open_log_folder(self):
            try:
                log_dir().mkdir(parents=True, exist_ok=True)
                os.startfile(str(log_dir()))
            except (OSError, AttributeError):
                messagebox.showerror('日志目录', '无法打开目录；请复制窗口显示的路径。')

        def refresh_logs(self):
            if self.log_window is None or not self.log_window.winfo_exists(): return
            try:
                path = log_dir() / 'runtime.log'
                with path.open('rb') as f:
                    f.seek(max(0, path.stat().st_size - 128 * 1024))
                    content = f.read().decode('utf-8', errors='replace')
            except OSError:
                content = '日志暂时无法读取，请检查目录写入权限。'
            if content != self.log_content:
                self.log_text.configure(state='normal')
                self.log_text.delete('1.0', 'end'); self.log_text.insert('end', content)
                self.log_text.configure(state='disabled'); self.log_text.see('end')
                self.log_content = content
            self.log_window.after(1000, self.refresh_logs)

        def insert(self, row):
            self.table.insert('', 'end', values=[row.get(k,'') for k in ('name','age','phones','emails')])

        def persist(self):
            tmp = self.cache.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.rows, ensure_ascii=False), encoding='utf-8')
            os.replace(tmp, self.cache)

        def buttons(self):
            running = self.worker is not None
            self.open_button.configure(state='disabled' if running else 'normal')
            self.proxy_entry.configure(state='disabled' if running else 'normal')
            self.engine_select.configure(state='disabled' if running else 'readonly')
            for button in (self.home_button, self.search_button, self.collect_button, self.resume_button):
                button.configure(state='normal' if running and not self.busy and not self.closing else 'disabled')

        def start(self):
            if self.worker: return
            try: proxy = proxy_config(self.proxy.get())
            except ValueError as exc:
                event('input_rejected', 'proxy')
                messagebox.showerror('代理格式', str(exc)); return
            self.busy = True
            self.worker = BrowserWorker(proxy, self.events, 'chrome')
            self.worker.start(); self.buttons(); self.status.set('正在启动浏览器…')

        def send(self, command, data=None):
            if self.worker and not self.busy:
                self.busy = True; self.buttons()
                self.worker.commands.put((command, data))

        def search(self):
            if not self.consent.get():
                messagebox.showinfo('确认测试资料', '请先确认资料授权'); return
            try: value = query_value(self.kind.get(), self.query.get())
            except ValueError as exc:
                event('input_rejected', 'search')
                messagebox.showerror('查询资料', str(exc)); return
            self.last_query = value
            self.status.set('正在提交查询…')
            self.send('search', (self.kind.get(), value))

        def collect(self):
            if not self.consent.get():
                messagebox.showinfo('确认测试资料', '请先确认资料授权'); return
            self.send('collect', self.last_query)

        def stop(self):
            if self.worker:
                event('stop_request', 'start')
                self.worker.stop_event.set(); self.busy = True; self.buttons()
                self.status.set('正在停止；当前网络操作超时后关闭浏览器…')

        def poll(self):
            try:
                while True:
                    kind, value = self.events.get_nowait()
                    if kind in ('status','ready','closed','error','warning') and value:
                        self.status.set(value)
                    if kind == 'error':
                        messagebox.showerror('浏览器启动失败', value)
                    if kind == 'warning':
                        messagebox.showwarning('浏览器操作提示', value)
                    if kind in ('error', 'warning'):
                        try:
                            (data_dir() / 'diagnostics.txt').write_text(value, encoding='utf-8')
                        except OSError: pass
                    if kind in ('idle','ready'): self.busy = False
                    if kind == 'ready' and self.auto_search.get() and self.query.get().strip() and self.consent.get():
                        self.search()
                    if kind == 'closed': self.worker = None; self.busy = False
                    if kind == 'row':
                        if not any(r.get('source_url') == value['source_url'] and r.get('query') == value['query'] for r in self.rows):
                            event('result_saved', 'ok')
                            self.rows.append(value); self.insert(value)
                            try: self.persist()
                            except OSError: messagebox.showerror('缓存失败', '无法保存本机缓存，请立即导出 Excel')
                    self.buttons()
            except queue.Empty: pass
            if self.closing and self.worker is None:
                self.root.destroy(); return
            self.root.after(100, self.poll)

        def export(self):
            if not self.rows:
                messagebox.showinfo('导出', '还没有采集结果'); return
            path = filedialog.asksaveasfilename(defaultextension='.xlsx', initialfile='TPS-results.xlsx', filetypes=[('Excel','*.xlsx')])
            if path:
                try:
                    export_xlsx(self.rows, path)
                    event('export_done', 'ok', count=len(self.rows))
                    self.status.set(f'已导出 {len(self.rows)} 条结果')
                except OSError:
                    event('export_error', 'failed')
                    messagebox.showerror('导出失败', '请关闭正在打开的 Excel，或更换保存目录')

        def clear(self):
            if messagebox.askyesno('清空结果', '确认删除本机缓存？已导出的 Excel 不会删除。'):
                try:
                    self.cache.unlink(missing_ok=True)
                    self.rows.clear()
                    self.table.delete(*self.table.get_children())
                    self.status.set('本机结果已清空')
                except OSError: messagebox.showerror('清空失败','缓存文件无法删除')

        def close(self):
            event('app_close', 'start')
            self.closing = True
            self.stop()
            if not self.worker: self.root.destroy()

    root = tk.Tk(); App(root); root.mainloop()


if __name__ == '__main__':
    if '--self-test' in sys.argv: self_test()
    else: main()

