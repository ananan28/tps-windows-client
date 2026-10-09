"""Single authorized lookup CLI using the Windows GUI's core."""
import os
import sys
from getpass import getpass
from browser import open_context, profile_dir, submit_search, AccessBlocked, error_message
from core import HOME, proxy_config, query_value
from diagnostic_capture import capture_failure
from runtime_log import event, setup_logging


def main():
    setup_logging()
    kind = '邮箱' if '--email' in sys.argv else '手机号'
    if input('仅查询自己的或已获授权的测试资料，确认请输入 YES：').strip() != 'YES':
        return 2
    value = query_value(kind, getpass('查询值（输入不回显）：'))
    proxy = proxy_config(os.environ.get('TPS_HTTP_PROXY', ''))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        context = open_context(p, proxy, 'chrome', profile_dir(proxy, 'chrome'))
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(7000)
            page.set_default_navigation_timeout(15000)
            from browser_diagnostics import attach_context_diagnostics
            attach_context_diagnostics(context)
            page.goto(HOME, wait_until='domcontentloaded')
            try:
                submit_search(page, kind, value)
                print('已提交；请在浏览器查看结果。')
            except AccessBlocked as exc:
                capture_failure(page, 'challenge')
                print(str(exc))
                input('人工处理后按回车检查一次；不自动操作验证码：')
                from browser import check_access
                check_access(page)
                if not exc.submitted:
                    submit_search(page, kind, value)
                print('阻断已解除；已发送的查询不会重复提交。')
            input('按回车关闭本次浏览器：')
        except Exception as exc:
            if 'page' in locals(): capture_failure(page, 'submission')
            print(error_message(exc, '操作失败'))
            return 1
        finally:
            context.close()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        sys.exit(2)
    except Exception as exc:
        event('operation_error', 'failed')
        print(error_message(exc, '启动失败'))
        sys.exit(1)
