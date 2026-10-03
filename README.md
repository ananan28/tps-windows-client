# TPS Windows Client 0.1.1

独立实现的 Windows x64 图形客户端。HTTP 认证代理、单线程可见 Chromium、单条手机号/邮箱查询、人工选择匹配详情、详情采集和 XLSX 导出。未复制参考仓库源码。

## 下载与使用

打开本仓库 Actions 的 `Windows test build`，选择成功运行，在 Artifacts 下载 `TPSWindowsClient-0.1.1-Windows-x64`。解压整个目录，运行 `TPSWindowsClient.exe`。包含运行时和 Chromium，无需安装 Python；不能只移动 EXE。

1. 填写自己的 HTTP 代理：`host:port:user:password`；留空直连。凭据不落盘。
2. 打开浏览器，网站验证请人工完成。
3. 在浏览器选择 Phone/Email 标签，软件填单条授权测试资料并查询。表单不兼容时可在浏览器手动查询。
4. 在浏览器选择正确人员的 View Details，点击软件的“采集当前详情”。
5. 核对数据并导出 Excel。停止关闭浏览器，缓存不清空；重新打开程序可恢复结果。

## 测试范围与限制

- 本地核心测试：代理验证、号码规范化、站点边界、验证页拒绝采集、JSON-LD 提取和 Excel 公式注入防护。
- Windows Actions：运行核心测试，构建包含浏览器的便携包，再实际启动打包 EXE 访问离线虚构详情、导出 XLSX 并验证 Tk 窗口。
- 不把离线构建通过描述为真实网站成功。用户已确认自己的 HTTP 代理可以手动访问详情页；本客户端的真实网站查询和字段准确性尚需用户 Windows 验收。
- 当前是单条查询/详情采集测试版，不是完整批量采集器。没有自动匹配人员、IP 轮换或验证码破解功能；姓名/地址字段随网站结构变化仍可能需要调整。
- 第一版只在识别到详情容器时采集；没有姓名、验证页或结果列表均拒绝保存。XLSX 来源 URL 和采集时间用于人工核对。
- 程序包未签名。浏览器运行占用本机资源；退出软件会关闭其浏览器。网络操作的停止最多等待当前操作超时。

## 本机数据

结果缓存：`%LOCALAPPDATA%\TPSWindowsClient\results.json`，包含采集资料，可在界面清空。仅保存在本机，无远程上传。代理凭据只在内存，不保存到 Git、缓存或日志。公开仓库严禁提交实际用户资料和凭据。

## 源码开发

Python 3.12：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m unittest discover -s tests -v
python app.py
```

浏览器 API 始终在独立单线程运行，通过队列与 Tk 主线程通信。停止不会清空结果；重复的相同查询/详情 URL 不重复添加。Excel 写入先保存临时文件再替换目标。

## 维护归属

用户指定由 2026-10-03 当前创建对话维护。其他 GPT 窗口未经用户转交请勿修改、推送、合并或触发构建；见 `AGENTS.md`。此约定不构成 GitHub 权限锁。

参考项目只用于此前可行性评估：https://github.com/qq1254870524/truepeoplesearch 。其许可证未明确，本项目没有引入其源码。

## 0.1.1 启动修复

首页加载超时或代理错误时保留浏览器窗口；启动失败弹出明确错误，不再被停止状态覆盖。诊断只保存错误类别，不保存代理凭据；位置 `%LOCALAPPDATA%\TPSWindowsClient\diagnostics.txt`。
