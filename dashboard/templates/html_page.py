# -*- coding: utf-8 -*-
"""Dashboard 前端页面加载器。

【v5.38.69 收敛】前端源码已从本文件的巨型 Python 字符串拆分为真实文件：
- dashboard/templates/index.html  运营主页面
- dashboard/templates/login.html  登录页
本模块只负责读取并保持原有导出（HTML_PAGE / LOGIN_PAGE）不变，
部署链路通过 deploy_vps.SCAN_DIR_EXTS 的 dashboard ".html" 映射上传。
"""

from pathlib import Path

_TEMPLATE_DIR = Path(__file__).parent

_FALLBACK_PAGE = (
    "<!DOCTYPE html><html lang=\"zh-CN\"><meta charset=\"UTF-8\">"
    "<body style=\"font-family:sans-serif;padding:2em\">"
    "页面资源缺失，请检查部署完整性（dashboard/templates/）。</body></html>"
)


def _load(name: str) -> str:
    path = _TEMPLATE_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        # 模板缺失属于部署事故：保底返回占位页避免 Dashboard 直接 500，同时留痕
        import logging
        logging.getLogger("dashboard.templates").error(f"前端模板读取失败: {name}: {e}")
        return _FALLBACK_PAGE


HTML_PAGE = _load("index.html")
LOGIN_PAGE = _load("login.html")
