from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QUrl


# 这里集中的是“页面入口元数据”，不是页面正文文案。
# Python 的子窗口服务需要用它找到 QML 文件和窗口标题；页面内部标题、说明、按钮文字仍放在 QML。
@dataclass(frozen=True)
class PageDefinition:
    key: str
    title: str
    qml_file: str
    icon: str


PAGE_DEFINITIONS: dict[str, PageDefinition] = {
    "home": PageDefinition("home", "首页", "HomePage.qml", "home"),
    "settings": PageDefinition("settings", "设置", "SettingsPage.qml", "settings"),
    "tools": PageDefinition("tools", "工具", "ToolsPage.qml", "tools"),
    "update": PageDefinition("update", "更新", "UpdatePage.qml", "update"),
    "about": PageDefinition("about", "关于", "AboutPage.qml", "about"),
    "inline-demo": PageDefinition("inline-demo", "页内子窗口", "InlineDemoPage.qml", "dialog"),
    "task-create": PageDefinition("task-create", "新建任务", "TaskCreatePage.qml", "tools"),
    "task-edit": PageDefinition("task-edit", "编辑任务", "TaskEditPage.qml", "tools"),
}

DEFAULT_PAGE_KEY = "home"
DEFAULT_CHILD_PAGE_KEY = "about"


def page_definition(page_key: str, *, child_default: bool = False) -> PageDefinition:
    # 主界面未知页面回首页；独立子窗口未知页面回关于页，避免打开空白窗口。
    fallback = DEFAULT_CHILD_PAGE_KEY if child_default else DEFAULT_PAGE_KEY
    return PAGE_DEFINITIONS.get(str(page_key or ""), PAGE_DEFINITIONS[fallback])


def page_title(page_key: str, *, child_default: bool = False) -> str:
    return page_definition(page_key, child_default=child_default).title


def page_icon(page_key: str, *, child_default: bool = False) -> str:
    return page_definition(page_key, child_default=child_default).icon


def page_qml_source(page_key: str, *, child_default: bool = False) -> str:
    return f"../pages/{page_definition(page_key, child_default=child_default).qml_file}"


def page_source_url(qml_dir: Path, page_key: str, *, child_default: bool = False) -> str:
    page = page_definition(page_key, child_default=child_default)
    return QUrl.fromLocalFile(str(qml_dir / "pages" / page.qml_file)).toString()
