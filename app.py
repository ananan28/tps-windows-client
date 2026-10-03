import json
import os
import queue
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'

from core import VERSION, proxy_config, query_value, export_xlsx
from browser import BrowserWorker


def data_dir():
    path = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TPSWindowsClient'
    path.mkdir(parents=True, exist_ok=True)
    return path


def self_test():
    """Offline bundled browser + actual XLSX smoke test; no real people or network."""
    from playwright.sync_api import sync_playwright
    from browser import SNAPSHOT_JS
    from core import extract
    import tempfile
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            page = b.new_page()
            page.route('https://www.truepeoplesearch.com/**', lambda route: route.fulfill(
                content_type='text/html', body='<div id="personDetails"><h1>Test Person</h1><a href="tel:2025550123">Test</a></div>'))
            page.goto('https://www.truepeoplesearch.com/test-detail')
            row = extract(page.evaluate(SNAPSHOT_JS))
            assert row['name'] == 'Test Person'
            assert row['phones'] == '2025550123'
            with tempfile.TemporaryDirectory() as d:
                dest = Path(d) / 'smoke.xlsx'
                export_xlsx([row], dest)
                assert dest.exists()
        finally: b.close()
    # Verify that the packaged Tcl/Tk runtime can create a window on Windows.
    import tkinter as tk
    root = tk.Tk(); root.withdraw(); root.update(); root.destroy()
    Path('self-test-result.json').write_text(json.dumps({
        'version': VERSION, 'offline_browser': 'passed', 'xlsx': 'passed',
        'tkinter': 'passed', 'live_site': 'not_tested'}), encoding='utf-8')


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
            self.cache = data_dir() / 'results.json'
            self.proxy = tk.StringVar()
            self.query = tk.StringVar()
            self.kind = tk.StringVar(value='手机号')
            self.consent = tk.BooleanVar()
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
            self.open_button = ttk.Button(tools, text='1. 打开浏览器', command=self.start); self.open_button.pack(side='left')
            self.home_button = ttk.Button(tools, text='返回首页', command=lambda: self.send('home')); self.home_button.pack(side='left', padx=5)
            ttk.Button(tools, text='停止浏览器', command=self.stop).pack(side='left')
            line = ttk.Frame(frame); line.pack(fill='x', pady=12)
            ttk.Combobox(line, values=['手机号', '邮箱'], textvariable=self.kind, state='readonly', width=9).pack(side='left')
            ttk.Entry(line, textvariable=self.query).pack(side='left', fill='x', expand=True, padx=8)
            self.search_button = ttk.Button(line, text='2. 查询', command=self.search); self.search_button.pack(side='left')
            self.collect_button = ttk.Button(line, text='3. 采集当前详情', command=self.collect); self.collect_button.pack(side='left', padx=5)
            ttk.Checkbutton(frame, text='我确认仅查询自己的或获得授权的测试资料', variable=self.consent).pack(anchor='w')
            ttk.Label(frame, text='在浏览器选择 Phone/Email 标签；结果页请自己选择正确人员，避免自动匹配错人。').pack(anchor='w', pady=6)
            self.table = ttk.Treeview(frame, columns=('name','age','phones','emails'), show='headings')
            for key, label in [('name','姓名'),('age','年龄'),('phones','电话'),('emails','邮箱')]:
                self.table.heading(key, text=label); self.table.column(key, width=180)
            self.table.pack(fill='both', expand=True, pady=8)
            bottom = ttk.Frame(frame); bottom.pack(fill='x')
            ttk.Button(bottom, text='4. 导出 Excel', command=self.export).pack(side='left')
            ttk.Button(bottom, text='清空本机结果', command=self.clear).pack(side='left', padx=8)
            ttk.Label(frame, textvariable=self.status, wraplength=980).pack(anchor='w', pady=(12,0))
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
            for button in (self.home_button, self.search_button, self.collect_button):
                button.configure(state='normal' if running and not self.busy and not self.closing else 'disabled')

        def start(self):
            if self.worker: return
            try: proxy = proxy_config(self.proxy.get())
            except ValueError as exc:
                messagebox.showerror('代理格式', str(exc)); return
            self.busy = True
            self.worker = BrowserWorker(proxy, self.events)
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
                messagebox.showerror('查询资料', str(exc)); return
            self.last_query = value
            self.send('search', (self.kind.get(), value))

        def collect(self):
            if not self.consent.get():
                messagebox.showinfo('确认测试资料', '请先确认资料授权'); return
            self.send('collect', self.last_query)

        def stop(self):
            if self.worker:
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
                    if kind in ('error', 'warning'):
                        try:
                            (data_dir() / 'diagnostics.txt').write_text(value, encoding='utf-8')
                        except OSError: pass
                    if kind in ('idle','ready'): self.busy = False
                    if kind == 'closed': self.worker = None; self.busy = False
                    if kind == 'row':
                        if not any(r.get('source_url') == value['source_url'] and r.get('query') == value['query'] for r in self.rows):
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
                try: export_xlsx(self.rows, path); self.status.set(f'已导出 {len(self.rows)} 条结果')
                except OSError: messagebox.showerror('导出失败', '请关闭正在打开的 Excel，或更换保存目录')

        def clear(self):
            if messagebox.askyesno('清空结果', '确认删除本机缓存？已导出的 Excel 不会删除。'):
                try:
                    self.cache.unlink(missing_ok=True)
                    self.rows.clear()
                    self.table.delete(*self.table.get_children())
                    self.status.set('本机结果已清空')
                except OSError: messagebox.showerror('清空失败','缓存文件无法删除')

        def close(self):
            self.closing = True
            self.stop()
            if not self.worker: self.root.destroy()

    root = tk.Tk(); App(root); root.mainloop()


if __name__ == '__main__':
    if '--self-test' in sys.argv: self_test()
    else: main()
