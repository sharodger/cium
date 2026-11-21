# -*- coding: utf-8 -*-
"""
app.py —— 业主维权AI助手 主系统入口（Kivy，PC/移动端共用）

主系统骨架：
  * 顶部状态栏：网络/后端、法规库版本、设备识别状态
  * 中部对话区：时间线展示消息（文字为主；图片/语音入口已预留）
  * 底部输入区：文字输入 + 发送 + 设置入口 + 语音/旁听占位按钮
  * 设置弹窗：法规库更新面板（复用 legal 子系统）+ 隐私数据清除 + 关于

线程模型：路由、法规检索等耗时操作放后台线程，
所有 UI 更新经 Clock.schedule_once 回主线程（Kivy 只能在主线程改控件）。

后续功能入口（本次只占位，不实现）：
  * 语音对话：底部「语音」按钮 -> _on_voice()
  * 旁听模式：底部「旁听」按钮 -> _on_monitor()
  * 图片识别：后续在输入区加图片按钮，接 Tesseract OCR

法规库子系统位于 legal/，其内部代码保持原样；本文件通过 sys.path 接入。
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEGAL_DIR = HERE / "legal"
sys.path.insert(0, str(HERE))        # 让 core 可导入
sys.path.insert(0, str(LEGAL_DIR))   # 让 legal 子系统平级导入生效（不改其内部代码）

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.properties import ObjectProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView

from core.router import MODULE_NAMES, route
from core.playbook import pick as pick_playbook
from core.templates import AnswerSections, render, BriefSections, render_brief
from device import DeviceManager
from database import LegalDatabase
from downloader import backend_name
from updater import LegalUpdateManager, UpdateError
from legal.ui.update_panel import UpdatePanel

APP_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# KV 布局
# ---------------------------------------------------------------------------

KV = r"""
<RootWidget>:
    orientation: 'vertical'

    BoxLayout:
        size_hint_y: None
        height: dp(62)
        padding: dp(12), dp(6)
        canvas.before:
            Color:
                rgba: 0.12, 0.30, 0.48, 1
            Rectangle:
                pos: self.pos
                size: self.size
        BoxLayout:
            orientation: 'vertical'
            Label:
                text: '业主维权AI助手'
                font_size: '18sp'
                bold: True
                color: 1, 1, 1, 1
                halign: 'left'
                size_hint_y: 0.55
            Label:
                text: root.status_line
                font_size: '11sp'
                color: 0.85, 0.90, 0.96, 1
                halign: 'left'
        Button:
            text: '设置 ⚙'
            size_hint_x: 0.22
            on_press: root.open_settings()

    ScrollView:
        id: transcript_view
        size_hint_y: 1
        bar_width: dp(4)
        canvas.before:
            Color:
                rgba: 0.99, 0.99, 0.99, 1
            Rectangle:
                pos: self.pos
                size: self.size
        Label:
            id: transcript
            text: root.transcript
            font_size: '14sp'
            color: 0.12, 0.12, 0.12, 1
            size_hint_y: None
            height: self.texture_size[1] + dp(20)
            text_size: self.width - dp(20), None
            halign: 'left'
            valign: 'top'

    BoxLayout:
        size_hint_y: None
        height: dp(56)
        padding: dp(8)
        spacing: dp(6)
        TextInput:
            id: entry
            hint_text: '说说你遇到的问题（文字）…'
            multiline: False
            on_text_validate: root.send()
        Button:
            text: '发送'
            size_hint_x: 0.18
            on_press: root.send()
        Button:
            text: '语音'
            size_hint_x: 0.16
            on_press: root.on_voice()
        Button:
            text: '旁听'
            size_hint_x: 0.16
            on_press: root.on_monitor()

<SettingsView>:
    title: '设置'
    size_hint: 0.94, 0.94
    auto_dismiss: True
    BoxLayout:
        orientation: 'vertical'
        padding: dp(10)
        spacing: dp(8)
        ScrollView:
            size_hint_y: 1
            BoxLayout:
                id: panel_host
                orientation: 'vertical'
                size_hint_y: None
                height: dp(620)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Button:
                text: '隐私清除'
                on_press: root.clear_privacy()
            Button:
                text: '关于'
                on_press: root.show_about()
            Button:
                text: '关闭'
                on_press: root.dismiss()
"""

# Kivy 默认 Roboto 字体不含中文字形，手机上会显示方块。
# 若构建流程已放入开源中文字体，就覆盖默认字体；没有时保持原样（降级不崩溃）。
FONT_FILE = HERE / "assets" / "fonts" / "DroidSansFallbackFull.ttf"
if FONT_FILE.exists():
    LabelBase.register(name="Roboto", fn_regular=str(FONT_FILE))

Builder.load_string(KV)


# ---------------------------------------------------------------------------
# 主界面
# ---------------------------------------------------------------------------

class RootWidget(BoxLayout):
    """主界面根组件。依赖由 App 注入，避免 KV 构建期访问未就绪对象。"""

    app_ref = ObjectProperty(None, allownone=True)
    status_line = StringProperty("法规库：- · 设备：-")
    transcript = StringProperty("")

    def __init__(self, app_ref=None, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        self._history: list[tuple[str, str]] = []  # (角色, 文本)
        self._welcome()

    # ----- 主线程调度 -----
    def _ui(self, fn, *args, **kwargs):
        Clock.schedule_once(lambda dt: fn(*args, **kwargs), 0)

    def _render_transcript(self) -> None:
        """把历史消息渲染成时间线文本。"""
        lines = []
        for role, text in self._history:
            prefix = "我" if role == "user" else "助手"
            lines.append(f"[{prefix}] {text}")
            lines.append("")
        self.transcript = "\n".join(lines)
        # 滚动到底部
        try:
            sv = self.ids.transcript_view
            sv.scroll_y = 0
        except Exception:
            pass

    def _welcome(self) -> None:
        self._history.append(("assistant",
            "我是业主维权AI助手，能帮你把问题拆成依据、步骤和文书。\n"
            "先说说你遇到什么事？文字描述即可。\n"
            "（仅供参考，重大事项请咨询执业律师或拨打 12348）"))
        self._render_transcript()

    def refresh_status(self) -> None:
        app = self.app_ref
        if not app:
            return
        stats = app.db.stats()
        self.status_line = (f"法规库 v{stats['law_version']} · "
                            f"{stats['law_count']} 条 · "
                            f"{app.device_manager.short_id()} · {backend_name()}")

    # ----- 发送（后台线程处理） -----
    def send(self) -> None:
        app = self.app_ref
        if not app:
            return
        text = self.ids.entry.text.strip()
        if not text:
            return
        self.ids.entry.text = ""
        self._history.append(("user", text))
        self._render_transcript()
        self._history.append(("assistant", "正在分析…"))
        self._render_transcript()

        def work():
            try:
                answer = app.answer(text)
            except Exception as e:
                answer = f"处理失败：{e}\n（可改用文字描述关键信息）"
            self._ui(self._replace_last_assistant, answer)

        threading.Thread(target=work, daemon=True, name="core-answer").start()

    def _replace_last_assistant(self, text: str) -> None:
        # 把最后的"正在分析…"替换成真实回答
        for i in range(len(self._history) - 1, -1, -1):
            if self._history[i][0] == "assistant":
                self._history[i] = ("assistant", text)
                break
        self._render_transcript()

    # ----- 后续功能占位（本次不实现） -----
    def on_voice(self) -> None:
        self._history.append(("assistant",
            "【语音对话】为后续功能，当前版本尚未实现，请先用文字描述。"
            "（后续将接入本地 Vosk 离线语音转写）"))
        self._render_transcript()

    def on_monitor(self) -> None:
        self._history.append(("assistant",
            "【旁听模式】为后续功能，当前版本尚未实现。"
            "（后续将用于实时记录与要点提示）"))
        self._render_transcript()

    # ----- 设置 -----
    def open_settings(self) -> None:
        app = self.app_ref
        if not app:
            return
        view = SettingsView(app_ref=app)
        panel = UpdatePanel(manager=app.update_manager,
                            device_manager=app.device_manager,
                            app_version=APP_VERSION)
        view.ids.panel_host.add_widget(panel)
        view.open()


class SettingsView(ModalView):
    """设置弹窗：法规库更新 + 隐私清除 + 关于。"""

    app_ref = ObjectProperty(None, allownone=True)

    def clear_privacy(self) -> None:
        """清除本地敏感数据（对话记录、上传材料），保留法规库。"""
        import sqlite3
        app = self.app_ref
        if not app:
            return
        try:
            # 对话记录只存在内存，重建即可
            app.root_widget._history.clear()
            app.root_widget._welcome()
            # 只重置对话，法规库保留
            self._append_log("已清除本地对话记录（法规库保留）。")
        except Exception as e:
            self._append_log(f"隐私清除失败：{e}")

    def show_about(self) -> None:
        self._append_log(
            f"业主维权AI助手 v{APP_VERSION}\n"
            "本地优先，法规库可离线更新。\n"
            "本工具提供信息整理与行动建议，不构成正式法律意见。"
        )

    def _append_log(self, text: str) -> None:
        """设置弹窗的消息入口：追加到主对话区时间线。"""
        app = self.app_ref
        if app and app.root_widget:
            app.root_widget._history.append(("assistant", text))
            app.root_widget._render_transcript()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class OwnerRightsApp(App):
    title = "业主维权AI助手"

    def build(self):
        app_dir = Path(self.user_data_dir)
        app_dir.mkdir(parents=True, exist_ok=True)

        # 设备初始化（跨设备复制检测）
        self.device_manager = DeviceManager(app_data_dir=app_dir)
        self.device_manager.initialize()

        # 法规库
        self.db = LegalDatabase(app_dir / "legal.db")

        # 更新引擎
        dist_dir = LEGAL_DIR / "dist"
        self.update_manager = LegalUpdateManager(
            db=self.db,
            app_data_dir=app_dir,
            version_url=(dist_dir / "version.json").as_uri() if dist_dir.exists() else "",
            package_base_url=dist_dir.as_uri() if dist_dir.exists() else "",
            app_version=APP_VERSION,
        )

        self.root_widget = RootWidget(app_ref=self)
        Clock.schedule_once(lambda dt: self.root_widget.refresh_status(), 0.1)
        return self.root_widget

    def answer(self, text: str) -> str:
        """
        内核主流程（后台线程调用）：
          路由 -> 要点补漏重排 -> 法规检索 -> 五块模板组装。
        旧八段式接口（AnswerSections/render）保留不动，供自测与后续复用。
        """
        # 1) 路由 + 要点补漏重排（把真正相关的模块排到前面）
        rr = route(text)
        codes, books = pick_playbook(text, rr.codes)
        label = ("[路由: 综合]" if codes == ["综合"]
                 else "[路由: " + "→".join(codes) + "]")

        # 2) 法规检索（LIKE 兜底，规避中文 FTS 分词问题）
        laws = _search_laws(self.db, text, limit=3)

        # 3) 法规命中时作为依据带出；空库明确标注待核实（不编造条款）
        judgments: list[str] = []
        if books:
            judgments.extend(books[0].judgments)
        if laws:
            refs = []
            for law in laws:
                loc = " · ".join(p for p in (law.law_name, law.part, law.article) if p)
                refs.append(loc)
            judgments.append("相关法规：" + "；".join(refs) + "（具体条款以现行文本为准）")
        else:
            judgments.append("具体法规条款待核实：请结合现行法规与当地规定。")

        primary = books[0] if books else None
        return render_brief(BriefSections(
            route_label=label,
            headline=primary.headline if primary else "",
            judgments=judgments,
            actions=primary.actions if primary else [],
            evidence=primary.evidence if primary else "",
            question=primary.question if primary else "",
            include_disclaimer=True,
        ))


def _search_laws(db: LegalDatabase, text: str, limit: int = 3) -> list:
    """
    本地法规检索：直接用 LIKE（中文 FTS5 默认分词器不按词切分，
    用 LIKE 更可靠）。取文本中 2 字片段做匹配，命中即返回。
    """
    if not text.strip():
        return []
    # 从输入里取若干 2 字词做关键词
    keys = [text[i:i + 2] for i in range(len(text) - 1)][:8]
    seen: set[str] = set()
    results = []
    with db._read() as conn:
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            like = f"%{key}%"
            rows = conn.execute(
                "SELECT * FROM laws WHERE content LIKE ? OR law_name LIKE ? "
                "OR keywords LIKE ? LIMIT ?",
                (like, like, like, limit),
            ).fetchall()
            for r in rows:
                if r["law_id"] not in {x.law_id for x in results}:
                    from database import Law
                    results.append(Law(**{k: r[k] for k in Law.__dataclass_fields__.keys()}))  # type: ignore[attr-defined]
            if len(results) >= limit:
                break
    return results[:limit]


if __name__ == "__main__":
    OwnerRightsApp().run()
