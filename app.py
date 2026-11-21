# -*- coding: utf-8 -*-
"""
app.py —— 业主维权AI助手 主系统入口（Kivy，PC/移动端共用）

界面（本版重做）：
  * 首页：按模块分类的卡片，点卡片带引导问题进对话；"其他/不确定"做引导
  * 对话页：用户/助手气泡分色区隔，可滚动
  * 设置弹窗：账号区（登录功能下一步接入）+ 法规库更新 + 关于 + 隐私清除
  * 顶部状态栏、底部工具按钮，统一卡片式工具软件观感

内核（route / playbook / templates / answer / _search_laws）保持原样，界面层只负责调用。
线程模型：耗时操作放后台线程，UI 更新经 Clock.schedule_once 回主线程。

登录（用户名+密码）为下一步功能，本版账号区会显示"尚未启用"，不假装已实现。
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
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import ObjectProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.widget import Widget
from kivy.factory import Factory
from kivy.uix.screenmanager import Screen, ScreenManager

from core.router import MODULE_NAMES, route
from core.playbook import pick as pick_playbook
from core.templates import AnswerSections, render, BriefSections, render_brief
from device import DeviceManager
from database import LegalDatabase
from downloader import backend_name
from updater import LegalUpdateManager, UpdateError
from legal.ui.update_panel import UpdatePanel

APP_VERSION = "1.0.0"

# 首页模块卡片：(代号, 标题, 说明, 点进去预填的引导问题)
MODULE_CARDS = [
    ("A", "财务核查", "公共收益、账目、物业费",
     "小区的公共收益和账目不公开，我应该怎么查？"),
    ("B", "物业合规", "业委会、合同、表决、涨价",
     "业委会没经过业主大会表决就做决定，怎么处理？"),
    ("C", "规划违建", "违建、改建、占用绿地",
     "有人占用公共绿地搭建，我该找谁、怎么办？"),
    ("D", "行政程序", "投诉、举报、复议、找哪个部门",
     "这个问题该向哪个部门投诉，答复期限怎么算？"),
    ("E", "证据固定", "拍照留痕、录音、送达",
     "我要留存证据和送达文书，怎么做才有效？"),
    ("F", "沟通博弈", "谈判、催办、质询话术",
     "物业拖着不办，我该怎么书面催办和质询？"),
    ("综合", "其他 / 不确定", "不知道属于哪一类，帮我引导",
     "我遇到一个问题，但不确定该问哪一类，帮我梳理一下。"),
]


# ---------------------------------------------------------------------------
# KV 布局
# ---------------------------------------------------------------------------

KV = r"""
<ChatBubble>:
    orientation: 'vertical'
    size_hint_y: None
    height: max(dp(40), self.minimum_height)
    padding: dp(10), dp(8)
    spacing: dp(2)
    canvas.before:
        Color:
            rgba: (0.20, 0.45, 0.72, 1) if root.role == 'user' else (0.90, 0.91, 0.93, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8)]
    Label:
        text: '我' if root.role == 'user' else '助手'
        font_size: '10sp'
        bold: True
        color: (0.85, 0.92, 1, 1) if root.role == 'user' else (0.35, 0.35, 0.35, 1)
        size_hint_y: None
        height: dp(16)
        halign: 'left'
    Label:
        id: lbl
        text: root.text_value
        font_size: '14sp'
        color: (1, 1, 1, 1) if root.role == 'user' else (0.12, 0.12, 0.12, 1)
        text_size: self.width, None
        size_hint_y: None
        height: self.texture_size[1]
        halign: 'left'
        valign: 'top'

<HomeScreen>:
    BoxLayout:
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
                Label:
                    text: root.status_line
                    font_size: '11sp'
                    color: 0.85, 0.90, 0.96, 1
                    halign: 'left'
            Button:
                text: '设置'
                size_hint_x: 0.20
                on_press: root.open_settings()
        Label:
            text: '选择你遇到的问题类型，点进去直接提问'
            size_hint_y: None
            height: dp(36)
            font_size: '13sp'
            color: 0.30, 0.34, 0.40, 1
            halign: 'left'
            padding_x: dp(12)
        ScrollView:
            id: home_scroll
            GridLayout:
                id: module_grid
                cols: 1
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(10)
                padding: dp(12)

<ChatScreen>:
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(6), dp(4)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0.12, 0.30, 0.48, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            Button:
                text: '< 首页'
                size_hint_x: 0.22
                on_press: root.go_home()
            Label:
                text: root.module_title
                font_size: '15sp'
                bold: True
                color: 1, 1, 1, 1
            Button:
                text: '设置'
                size_hint_x: 0.20
                on_press: root.open_settings()
        ScrollView:
            id: transcript_view
            GridLayout:
                id: bubbles
                cols: 1
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(8)
                padding: dp(10)
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
                size_hint_x: 0.20
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
            id: settings_scroll
            BoxLayout:
                id: panel_host
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(10)
                padding: dp(6)
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
# 首页
# ---------------------------------------------------------------------------

class HomeScreen(Screen):
    """模块分类首页：点卡片带引导问题进对话。"""

    status_line = StringProperty("法规库：-")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Clock.schedule_once(lambda dt: self._build_cards(), 0)

    def _build_cards(self) -> None:
        """把六个模块 + 其他，做成卡片按钮。"""
        grid = self.ids.module_grid
        if grid.children:  # 避免重复构建
            return
        for code, title, desc, question in MODULE_CARDS:
            btn = Button(
                text=f"{code}. {title}\n{desc}",
                size_hint_y=None,
                height=dp(72),
                background_color=(0.96, 0.97, 0.98, 1),
                color=(0.12, 0.18, 0.26, 1),
                halign="left",
                valign="middle",
            )
            btn.bind(on_press=lambda inst, q=question, t=title: self._enter(q, t))
            grid.add_widget(btn)

    def _enter(self, question: str, title: str) -> None:
        app = App.get_running_app()
        chat = app.root_widget.get_screen("chat")
        chat.start_conversation(question, title)
        self.manager.current = "chat"

    def open_settings(self) -> None:
        app = App.get_running_app()
        if app:
            app.open_settings()

    def refresh_status(self, text: str) -> None:
        self.status_line = text


# ---------------------------------------------------------------------------
# 对话页
# ---------------------------------------------------------------------------

class ChatBubble(BoxLayout):
    """一条气泡消息：role=user 蓝底靠右，role=assistant 灰底靠左。"""
    role = StringProperty("assistant")
    text_value = StringProperty("")


class ChatScreen(Screen):
    """对话页：气泡列表 + 输入框；内核计算放后台线程。"""

    module_title = StringProperty("对话")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._history: list[tuple[str, str]] = []  # (角色, 文本)

    def start_conversation(self, question: str, title: str) -> None:
        """从首页进来：设置模块标题、预填引导问题、清空历史并给欢迎语。"""
        self.module_title = title
        self.ids.entry.text = question
        self._history = []
        self._history.append(("assistant",
            "已按「" + title + "」为你准备了一个问题，可直接发送或修改后再发。\n"
            "（仅供参考，重大事项请咨询执业律师或拨打 12348）"))
        self._render_transcript()

    def _ui(self, fn, *args, **kwargs):
        Clock.schedule_once(lambda dt: fn(*args, **kwargs), 0)

    def _render_transcript(self) -> None:
        """把历史渲染成气泡列表；每次全量重建，条目不多，简单可靠。"""
        host = self.ids.bubbles
        host.clear_widgets()
        for role, text in self._history:
            row = BoxLayout(size_hint_y=None, height=dp(44))
            bubble = Factory.ChatBubble(role=role, text_value=text, size_hint_x=0.86)
            # 用户靠右：左侧留白；助手靠左：右侧留白
            if role == "user":
                row.add_widget(Widget(size_hint_x=0.14))
                row.add_widget(bubble)
            else:
                row.add_widget(bubble)
                row.add_widget(Widget(size_hint_x=0.14))
            # 行高随气泡内容自适应
            bubble.bind(height=lambda inst, val: setattr(row, "height", val + dp(8)))
            row.height = bubble.height + dp(8)
            host.add_widget(row)
        # 滚到底部
        try:
            self.ids.transcript_view.scroll_y = 0
        except Exception:
            pass

    def go_home(self) -> None:
        self.manager.current = "home"

    def open_settings(self) -> None:
        app = App.get_running_app()
        if app:
            app.open_settings()

    def send(self) -> None:
        app = App.get_running_app()
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
        for i in range(len(self._history) - 1, -1, -1):
            if self._history[i][0] == "assistant":
                self._history[i] = ("assistant", text)
                break
        self._render_transcript()

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


# ---------------------------------------------------------------------------
# 设置弹窗
# ---------------------------------------------------------------------------

class SettingsView(ModalView):
    """设置弹窗：账号区（未启用）+ 法规库更新 + 关于 + 隐私清除。"""

    app_ref = ObjectProperty(None, allownone=True)

    def build_sections(self) -> None:
        """按分区组装设置内容。"""
        host = self.ids.panel_host
        host.clear_widgets()

        def section(title: str, body: str) -> None:
            head = Label(text=title, font_size="15sp", bold=True,
                         color=(0.12, 0.30, 0.48, 1), size_hint_y=None,
                         height=dp(28), halign="left")
            txt = Label(text=body, font_size="12sp",
                        color=(0.20, 0.22, 0.25, 1), size_hint_y=None,
                        height=max(dp(44), dp(18) * (body.count("\n") + 1)),
                        halign="left", valign="top")
            txt.text_size = (None, None)
            host.add_widget(head)
            host.add_widget(txt)

        section("账号与安全", "当前为单机本地使用，账号登录尚未启用（下一步接入）。\n"
                "本工具不上传你的对话内容。")
        section("模块说明", "A 财务核查 · B 物业合规 · C 规划违建 · D 行政程序\n"
                "E 证据固定 · F 沟通博弈 · 其他：不确定时帮你引导归类")

        app = self.app_ref
        if app:
            panel = UpdatePanel(manager=app.update_manager,
                                device_manager=app.device_manager,
                                app_version=APP_VERSION)
            host.add_widget(panel)

        section("关于", f"业主维权AI助手 v{APP_VERSION}\n"
                "本地优先，法规库可离线更新。\n"
                "本工具提供信息整理与行动建议，不构成正式法律意见。")

    def clear_privacy(self) -> None:
        """清除本地对话记录（内存），保留法规库。"""
        app = self.app_ref
        if not app:
            return
        try:
            app.chat_screen._history.clear()
            app.chat_screen._history.append(("assistant",
                "已清除本地对话记录（法规库保留）。"))
            app.chat_screen._render_transcript()
        except Exception as e:
            self._append_log(f"隐私清除失败：{e}")

    def show_about(self) -> None:
        self._append_log(
            f"业主维权AI助手 v{APP_VERSION}\n"
            "本地优先，法规库可离线更新。\n"
            "本工具提供信息整理与行动建议，不构成正式法律意见。")

    def _append_log(self, text: str) -> None:
        app = self.app_ref
        if app and app.chat_screen:
            app.chat_screen._history.append(("assistant", text))
            app.chat_screen._render_transcript()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class OwnerRightsApp(App):
    title = "业主维权AI助手"

    def build(self):
        # Android 软键盘弹出时把输入框顶到键盘上方，避免"看不见输入的字"
        Window.softinput_mode = "below_target"

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

        # 首页 + 对话页（KV 里不能直接嵌 Screen，必须在代码里 add）
        root = ScreenManager()
        home = HomeScreen(name="home")
        chat = ChatScreen(name="chat")
        root.add_widget(home)
        root.add_widget(chat)
        root.current = "home"
        self.root_widget = root
        self.home_screen = home
        self.chat_screen = chat

        Clock.schedule_once(lambda dt: self.refresh_status(), 0.1)
        return root

    def refresh_status(self) -> None:
        stats = self.db.stats()
        updated = (stats.get("last_update_at") or "")[:16].replace("T", " ")
        text = (f"法规库 v{stats['law_version']} · {stats['law_count']} 条 · "
                f"{self.device_manager.short_id()} · {backend_name()}")
        if updated:
            text += f" · 更新于 {updated}"
        self.home_screen.refresh_status(text)

    def open_settings(self) -> None:
        view = SettingsView(app_ref=self)
        view.build_sections()
        view.open()

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
