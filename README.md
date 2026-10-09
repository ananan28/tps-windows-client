# TPS Windows Client / 标准 Playwright QA 源码 0.1.12

完整工程包含现有 Windows GUI、独立查询入口 crawler.py、标准测试入口 qa_test.py、依赖和测试。不包含浏览器二进制、用户代理凭据、个人查询结果或日志。使用 Python 3.12 和本机 Google Chrome。

## 双击启动（Windows）

先完整解压 ZIP，安装 Python 3.12（勾选 Python Launcher 和 Tcl/Tk）及 Google Chrome，然后双击 `start.bat`。无需管理员权限。

脚本在工程目录创建 `.venv`，首次联网安装 requirements.txt 中的依赖并打开 GUI。以后直接启动；依赖文件变更或模块缺失时重新安装。安装失败下次可重试。不会下载或打包 Chromium。启动失败会保留窗口显示原因；不要在 ZIP 预览中直接运行。

`start.bat --check` 仅检查和准备环境，不打开 GUI，失败返回非零退出码且不暂停，适合 CI。启动安装步骤显示在控制台；软件运行日志仍由 GUI 的日志按钮查看。

## 手动安装

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

默认使用已安装 Chrome，无需下载 Chromium。如果自行选择 `--browser chromium`，先用同一 Python 执行 `-m playwright install chromium`。

## 先运行标准 QA（不访问真实网站）

```powershell
.\.venv\Scripts\python.exe qa_test.py --self-test --headless --submit
```

本地 fixture 模拟：Phone 按钮先显示、约 1 秒后初始化并启用、点击后输入框延迟显示。使用虚构测试号码，所有网络由 route 拦截；测试不会操作生产环境验证码。

## 配置测试页面

```powershell
.\.venv\Scripts\python.exe qa_test.py --url https://your-test-site.example/ --tab-selector "#phone-tab" --input-selector "input[type=tel]"
```

默认只切换标签、填入虚构值并断言，不提交。确实需要提交时添加 `--submit --submit-selector "button[type=submit]" --success-selector "#success"`；成功断言应使用你测试页面的真实元素。通过 `--ready-selector` 指定自己应用的初始化标志。不要把个人查询值放进命令行；`--value` 只用于合成测试数据。

等待逻辑：共享 20 秒控件期限；expect 检查 visible/enabled/editable；trial click 检查稳定和事件可达；点击/填充使用 Playwright 自动等待。没有 time.sleep 或固定等待作为页面就绪判断。普通 Chrome 参数、独立 BrowserContext，不修改 User-Agent、TLS、Canvas、WebGL 或 webdriver。

## 固定 HTTP 代理

```powershell
$env:TPS_HTTP_PROXY = 'example.test:8080:example_user:example_password'
.\.venv\Scripts\python.exe qa_test.py --self-test --headless
```

支持 host:port、host:port:user:password 和 http://user:password@host:port。TLS 由正常 Chrome 完成，不做握手指纹伪造。代理不轮换，密码不写入日志。示例文件 `.env.example` 不会自动载入。GUI 仍在界面输入代理。

## 启动原有客户端与独立查询入口

```powershell
.\.venv\Scripts\python.exe app.py
.\.venv\Scripts\python.exe crawler.py
```

crawler.py 在内存中读取查询值并自动提交一次；GUI 保留授权确认、自动查询、人工验证暂停/继续、本机缓存与 Excel 导出。GUI 的控件准备最多三轮显式条件等待，只重选标签；提交后的未知状态不会重发。此版单线程，不包含批量查询、多开或 CSV 导出。

## 故障与诊断

标准 QA 返回码：0 通过，1 失败。默认 logs/qa/failure.json 记录阶段与错误类型；failure.png 为全页截图（输入框遮盖），failure.html 为去除输入值、链接、脚本的 DOM 结构。截图中的其他页面文字仍会保留，诊断仅留本机。每次运行建议使用独立 --output 目录。

GUI 的网络/控件/验证码故障不再弹出阻塞式 warning 对话框，而在状态栏显示并写入运行日志。最新 failure 证据位于 %LOCALAPPDATA%/TPSWindowsClient/logs/failure；首页及 InternalCaptcha 页保存遮罩截图和脱敏 DOM，结果页只保存元数据。诊断写入失败不会终止浏览器线程。

验证码、403、429 作为访问阻断处理，不当作空结果。不自动点击验证、不反复刷新、不换 IP 规避限制。人工验证完成后可检查一次并继续未提交任务。已发送的任务不会重复发送。

## 重构关系

app.py GUI 和 crawler.py -> browser.py（初始化、验证门控、显式等待、单次提交）
browser.py -> browser_diagnostics.py（被动资源/错误码观察）+ runtime_log.py（轮换日志）+ diagnostic_capture.py（本机故障证据）
core.py -> 输入校验、详情提取、Excel 输出
qa_test.py -> 独立干净会话、断言、失败证据；tests/ -> 纯单元测试

## 验证与限制

运行单元测试：`python -m unittest discover -s tests -v`。
Windows Actions 验证实际 EXE、离线异步页面、QA 成功/故障路径、Defender、下载后 EXE；证据属于离线测试，不代表真实网站验证或人员查询成功。生产环境的人机验证是否通过仍未验证，此源码不是 Cloudflare 验证修复或绕过包。

Playwright 文档：https://playwright.dev/python/docs/actionability
显式断言：https://playwright.dev/python/docs/api/class-locatorassertions
Cloudflare 支持环境：https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/
