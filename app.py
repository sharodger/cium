# -*- coding: utf-8 -*-
"""
app.py —— 业主维权AI助手 主系统入口（Kivy，PC/移动端共用）

界面（本版：豆包风浅色改造）：
  * 首页：按模块分类的白色圆角卡片，点进去直接空白输入（不再预填示例问题）
  * 对话页：用户/助手气泡分色区隔、可滚动；长按气泡复制整条回答
  * 底栏两行：输入+发送 / 上传+粘贴+识图+文书+语音+旁听
  * 账号页：本地用户名+密码，首次注册、之后登录（忘记密码只能清数据重置）
  * 设置弹窗：账号信息 + 模块说明 + 能力状态 + 法规库更新 + 关于 + 隐私清除
  * 识图弹窗：选材料类型 + 手动录入字段 -> 结构化表 + 证据要点，可复制

内核（route / playbook / templates / answer / _search_laws）保持原样，界面层只负责调用。
线程模型：耗时操作放后台线程，UI 更新经 Clock.schedule_once 回主线程。

登录是本机使用门槛，不是安全边界：账号哈希存在本地，忘记密码无法找回。
上传边界：只调系统选择器、记录文件名，不读取图片/文档内容，不做 OCR。
识图边界：只处理手动录入的文字（core/ocrkit.py 规则层），不读图、不自动识别；
         真正的图像识别需 Tesseract 引擎（待办），届时可直接复用本规则层。
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
from kivy.core.clipboard import Clipboard
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import ObjectProperty, StringProperty, ListProperty
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
from core.auth import LocalAuth, AuthError
from core.attach import select_file as attach_select_file
from core.evidence import detect_entities, recap_question
from core.docgen import DocRequest, generate as generate_doc, describe_result as describe_doc
from core.ocrkit import (available_types as ocr_types, DOC_SPECS as OCR_SPECS,
                         parse_manual_entry, render_material_table,
                         evidence_tip, degrade_notice)
from device import DeviceManager
from database import LegalDatabase
from downloader import backend_name
from updater import LegalUpdateManager, UpdateError
from legal.ui.update_panel import UpdatePanel

APP_VERSION = "1.0.0"

# 首页模块卡片：(代号, 标题, 说明)。
# 注意：点卡片不再预填示例问题，进入对话页后由用户自己描述。
MODULE_CARDS = [
    ("A", "财务核查", "公共收益、账目、物业费"),
    ("B", "物业合规", "业委会、合同、表决、涨价"),
    ("C", "规划违建", "违建、改建、占用绿地"),
    ("D", "行政程序", "投诉、举报、复议、找哪个部门"),
    ("E", "证据固定", "拍照留痕、录音、送达"),
    ("F", "沟通博弈", "谈判、催办、质询话术"),
    ("综合", "其他 / 不确定", "不知道属于哪一类，帮我引导"),
]


# ---------------------------------------------------------------------------
# KV 布局
# ---------------------------------------------------------------------------

KV = r"""
<AuthScreen>:
    BoxLayout:
        orientation: 'vertical'
        padding: dp(20), dp(16)
        spacing: dp(10)
        canvas.before:
            Color:
                rgba: 0.97, 0.98, 0.99, 1
            Rectangle:
                pos: self.pos
                size: self.size
        Widget:
            size_hint_y: 0.15
        Label:
            text: '业主维权AI助手'
            font_size: '22sp'
            bold: True
            color: 0.12, 0.30, 0.48, 1
            size_hint_y: None
            height: dp(40)
        Label:
            text: root.mode_hint
            font_size: '13sp'
            color: 0.35, 0.38, 0.42, 1
            size_hint_y: None
            height: dp(30)
        BoxLayout:
            size_hint_y: None
            height: dp(44)
            Label:
                text: '用户名'
                size_hint_x: 0.28
                font_size: '14sp'
                color: 0.2, 0.2, 0.2, 1
            TextInput:
                id: user
                multiline: False
                font_size: '15sp'
        BoxLayout:
            size_hint_y: None
            height: dp(44)
            Label:
                text: '密码'
                size_hint_x: 0.28
                font_size: '14sp'
                color: 0.2, 0.2, 0.2, 1
            TextInput:
                id: pwd
                multiline: False
                password: True
                font_size: '15sp'
        Button:
            id: primary
            text: root.primary_text
            size_hint_y: None
            height: dp(48)
            background_color: 0.12, 0.30, 0.48, 1
            color: 1, 1, 1, 1
            on_press: root.submit()
        Label:
            id: message
            text: root.message
            font_size: '12sp'
            color: 0.75, 0.25, 0.25, 1
            size_hint_y: None
            height: dp(40)
        Label:
            text: '提示：本机账号仅作使用门槛，忘记密码无法找回，只能清除应用数据重置。'
            font_size: '11sp'
            color: 0.45, 0.45, 0.45, 1
            size_hint_y: None
            height: dp(46)
            halign: 'left'
            valign: 'top'
            text_size: self.width, None
        Widget:
            size_hint_y: 0.25

<ChatBubble>:
    orientation: 'vertical'
    size_hint_y: None
    height: max(dp(44), self.minimum_height)
    padding: dp(10), dp(8)
    spacing: dp(2)
    canvas.before:
        Color:
            rgba: (0.22, 0.51, 0.90, 1) if root.role == 'user' else (1, 1, 1, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
    Label:
        text: '我' if root.role == 'user' else '助手 · 长按复制'
        font_size: '10sp'
        bold: True
        color: (0.90, 0.95, 1, 1) if root.role == 'user' else (0.45, 0.50, 0.58, 1)
        size_hint_y: None
        height: dp(16)
        halign: 'left'
    Label:
        id: lbl
        text: root.text_value
        font_size: '14sp'
        line_height: 1.35
        color: (1, 1, 1, 1) if root.role == 'user' else (0.15, 0.20, 0.28, 1)
        text_size: self.width, None
        size_hint_y: None
        height: self.texture_size[1]
        halign: 'left'
        valign: 'top'

<HomeScreen>:
    canvas.before:
        Color:
            rgba: 0.96, 0.97, 0.99, 1
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(64)
            padding: dp(12), dp(6)
            canvas.before:
                Color:
                    rgba: 1, 1, 1, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            BoxLayout:
                orientation: 'vertical'
                Label:
                    text: '业主维权AI助手'
                    font_size: '18sp'
                    bold: True
                    color: 0.10, 0.20, 0.33, 1
                    halign: 'left'
                Label:
                    text: root.status_line
                    font_size: '11sp'
                    color: 0.40, 0.47, 0.56, 1
                    halign: 'left'
            Button:
                text: '设置'
                size_hint_x: 0.20
                background_normal: ''
                background_color: 0.20, 0.45, 0.85, 1
                color: 1, 1, 1, 1
                on_press: root.open_settings()
        Label:
            text: '选择你遇到的问题类型，点进去直接描述'
            size_hint_y: None
            height: dp(36)
            font_size: '13sp'
            color: 0.28, 0.34, 0.42, 1
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
    canvas.before:
        Color:
            rgba: 0.96, 0.97, 0.99, 1
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            padding: dp(6), dp(4)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 1, 1, 1, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            Button:
                text: '< 首页'
                size_hint_x: 0.22
                background_normal: ''
                background_color: 0.20, 0.45, 0.85, 1
                color: 1, 1, 1, 1
                on_press: root.go_home()
            Label:
                text: root.module_title
                font_size: '15sp'
                bold: True
                color: 0.10, 0.20, 0.33, 1
            Button:
                text: '设置'
                size_hint_x: 0.20
                background_normal: ''
                background_color: 0.20, 0.45, 0.85, 1
                color: 1, 1, 1, 1
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
            orientation: 'vertical'
            size_hint_y: None
            height: dp(100)
            padding: dp(6), dp(4)
            spacing: dp(4)
            BoxLayout:
                size_hint_y: None
                height: dp(46)
                spacing: dp(6)
                TextInput:
                    id: entry
                    hint_text: '说说你遇到的问题（文字）…'
                    multiline: False
                    on_text_validate: root.send()
                Button:
                    text: '发送'
                    size_hint_x: 0.20
                    background_normal: ''
                    background_color: 0.20, 0.45, 0.85, 1
                    color: 1, 1, 1, 1
                    on_press: root.send()
            BoxLayout:
                size_hint_y: None
                height: dp(42)
                spacing: dp(6)
                Button:
                    text: '上传'
                    background_normal: ''
                    background_color: 0.93, 0.95, 0.98, 1
                    color: 0.20, 0.40, 0.70, 1
                    on_press: root.on_upload()
                Button:
                    text: '粘贴'
                    background_normal: ''
                    background_color: 0.93, 0.95, 0.98, 1
                    color: 0.20, 0.40, 0.70, 1
                    on_press: root.on_paste()
                Button:
                    text: '识图'
                    background_normal: ''
                    background_color: 0.20, 0.45, 0.85, 1
                    color: 1, 1, 1, 1
                    on_press: root.on_ocr()
                Button:
                    text: '文书'
                    background_normal: ''
                    background_color: 0.20, 0.45, 0.85, 1
                    color: 1, 1, 1, 1
                    on_press: root.on_document()
                Button:
                    text: '语音'
                    background_normal: ''
                    background_color: 0.93, 0.95, 0.98, 1
                    color: 0.20, 0.40, 0.70, 1
                    on_press: root.on_voice()
                Button:
                    text: '旁听'
                    background_normal: ''
                    background_color: 0.93, 0.95, 0.98, 1
                    color: 0.20, 0.40, 0.70, 1
                    on_press: root.on_monitor()

<OcrView>:
    title: '识图辅助（手动录入）'
    size_hint: 0.95, 0.92
    auto_dismiss: True
    BoxLayout:
        orientation: 'vertical'
        padding: dp(10)
        spacing: dp(6)
        Label:
            text: root.degrade_hint
            font_size: '12sp'
            color: 0.75, 0.30, 0.20, 1
            size_hint_y: None
            height: dp(40)
            text_size: self.width, None
        ScrollView:
            GridLayout:
                cols: 1
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(6)
                Label:
                    text: '① 选择材料类型'
                    size_hint_y: None
                    height: dp(22)
                    font_size: '12sp'
                    color: 0.3, 0.35, 0.42, 1
                    halign: 'left'
                Spinner:
                    id: doc_type
                    text: '银行流水/对账单'
                    values: root.type_list
                    size_hint_y: None
                    height: dp(40)
                    on_text: root.on_type_change(self.text)
                Label:
                    id: field_hint
                    text: root.field_hint
                    font_size: '11sp'
                    color: 0.35, 0.42, 0.5, 1
                    size_hint_y: None
                    height: dp(52)
                    text_size: self.width, None
                Label:
                    text: '② 手动录入（每行一条：字段名：值）'
                    size_hint_y: None
                    height: dp(22)
                    font_size: '12sp'
                    color: 0.3, 0.35, 0.42, 1
                    halign: 'left'
                TextInput:
                    id: entry
                    hint_text: '如：\n金额：35000元\n交易日期：2026-03-05\n对方户名：XX物业'
                    size_hint_y: None
                    height: dp(130)
                    font_size: '13sp'
                Label:
                    text: '③ 整理结果（表格 + 证据要点）'
                    size_hint_y: None
                    height: dp(22)
                    font_size: '12sp'
                    color: 0.3, 0.35, 0.42, 1
                    halign: 'left'
                TextInput:
                    id: result
                    readonly: True
                    text: root.result_text
                    size_hint_y: None
                    height: dp(120)
                    font_size: '12sp'
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Button:
                text: '关闭'
                on_press: root.dismiss()
            Button:
                text: '复制结果'
                background_normal: ''
                background_color: 0.93, 0.95, 0.98, 1
                color: 0.20, 0.40, 0.70, 1
                on_press: root.copy_result()
            Button:
                text: '整理成表'
                background_normal: ''
                background_color: 0.20, 0.45, 0.85, 1
                color: 1, 1, 1, 1
                on_press: root.build()

<DocView>:
    title: '生成文书'
    size_hint: 0.95, 0.92
    auto_dismiss: True
    BoxLayout:
        orientation: 'vertical'
        padding: dp(10)
        spacing: dp(6)
        ScrollView:
            GridLayout:
                cols: 1
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(6)
                Label:
                    text: '文书类型'
                    size_hint_y: None
                    height: dp(22)
                    font_size: '12sp'
                    color: 0.3, 0.35, 0.42, 1
                    halign: 'left'
                TextInput:
                    id: doc_type
                    text: '财务质询函'
                    size_hint_y: None
                    height: dp(38)
                    multiline: False
                Label:
                    text: '收件方全称'
                    size_hint_y: None
                    height: dp(22)
                    font_size: '12sp'
                    color: 0.3, 0.35, 0.42, 1
                    halign: 'left'
                TextInput:
                    id: party
                    hint_text: '如：XX区城管局'
                    size_hint_y: None
                    height: dp(38)
                    multiline: False
                Label:
                    text: '事实'
                    size_hint_y: None
                    height: dp(22)
                    font_size: '12sp'
                    color: 0.3, 0.35, 0.42, 1
                    halign: 'left'
                TextInput:
                    id: fact
                    hint_text: '发生了什么'
                    size_hint_y: None
                    height: dp(64)
                Label:
                    text: '依据（不确定可留空，将标待核实）'
                    size_hint_y: None
                    height: dp(22)
                    font_size: '12sp'
                    color: 0.3, 0.35, 0.42, 1
                    halign: 'left'
                TextInput:
                    id: basis
                    hint_text: '条款号与内容摘要'
                    size_hint_y: None
                    height: dp(56)
                Label:
                    text: '请求'
                    size_hint_y: None
                    height: dp(22)
                    font_size: '12sp'
                    color: 0.3, 0.35, 0.42, 1
                    halign: 'left'
                TextInput:
                    id: request
                    hint_text: '要求对方做什么'
                    size_hint_y: None
                    height: dp(56)
                Label:
                    text: '答复时限'
                    size_hint_y: None
                    height: dp(22)
                    font_size: '12sp'
                    color: 0.3, 0.35, 0.42, 1
                    halign: 'left'
                TextInput:
                    id: deadline
                    hint_text: '如：收到本函七日内'
                    size_hint_y: None
                    height: dp(38)
                    multiline: False
                Label:
                    id: message
                    text: root.message
                    font_size: '12sp'
                    color: 0.75, 0.25, 0.25, 1
                    size_hint_y: None
                    height: dp(40)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Button:
                text: '关闭'
                on_press: root.dismiss()
            Button:
                text: '生成文书'
                background_normal: ''
                background_color: 0.20, 0.45, 0.85, 1
                on_press: root.generate()

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
# 登录 / 注册页
# ---------------------------------------------------------------------------

class AuthScreen(Screen):
    """本地账号页：首次注册，之后登录。成功切到首页。"""

    mode_hint = StringProperty("")
    primary_text = StringProperty("")
    message = StringProperty("")
    is_register_mode = False

    def prepare(self, register_mode: bool, username: str = "") -> None:
        self.is_register_mode = register_mode
        self.mode_hint = ("首次使用，请设置用户名和密码" if register_mode
                          else f"欢迎回来，{username}，请输入密码登录")
        self.primary_text = "注册并进入" if register_mode else "登录"
        self.message = ""
        self.ids.user.text = "" if register_mode else username
        self.ids.pwd.text = ""
        # 注册时用户名可编辑；登录时锁定为已注册用户名
        self.ids.user.disabled = not register_mode

    def submit(self) -> None:
        app = App.get_running_app()
        auth: LocalAuth = app.auth
        username = self.ids.user.text.strip()
        password = self.ids.pwd.text
        try:
            if self.is_register_mode:
                auth.register(username, password)
            else:
                if not auth.verify(username, password):
                    self.message = "用户名或密码错误，请重试"
                    return
        except AuthError as e:
            self.message = str(e)
            return
        self.message = ""
        self.manager.current = "home"


# ---------------------------------------------------------------------------
# 首页
# ---------------------------------------------------------------------------

class HomeScreen(Screen):
    """模块分类首页：点卡片进对话，由用户自己描述问题（不再预填示例）。"""

    status_line = StringProperty("法规库：-")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Clock.schedule_once(lambda dt: self._build_cards(), 0)

    def _build_cards(self) -> None:
        """把六个模块 + 其他，做成白色圆角卡片（key：清空默认纹理否则发灰）。"""
        grid = self.ids.module_grid
        if grid.children:  # 避免重复构建
            return
        for code, title, desc in MODULE_CARDS:
            btn = Button(
                text=f"{code}. {title}\n[size=12]{desc}[/size]",
                size_hint_y=None,
                height=dp(72),
                background_normal="",          # 关键：去掉 Kivy 默认灰纹理
                background_color=(1, 1, 1, 1),  # 纯白卡片
                color=(0.15, 0.25, 0.38, 1),    # 深色字，清晰
                halign="left",
                valign="middle",
                markup=True,                     # 让 [size=12] 生效
            )
            btn.bind(on_press=lambda inst, t=title: self._enter(t))
            grid.add_widget(btn)

    def _enter(self, title: str) -> None:
        app = App.get_running_app()
        chat = app.root_widget.get_screen("chat")
        chat.start_conversation(title)
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
    """一条气泡消息：role=user 蓝底靠右，role=assistant 白底靠左；长按复制。"""
    role = StringProperty("assistant")
    text_value = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._press_event = None   # 长按计时器
        self._touch_origin = (0, 0)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._touch_origin = touch.pos
            self._press_event = Clock.schedule_once(lambda dt: self._copy(), 0.8)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        # 手指移动超过阈值 = 用户在滚动，取消长按，避免误复制
        if self._press_event and (
            abs(touch.x - self._touch_origin[0]) > dp(8)
            or abs(touch.y - self._touch_origin[1]) > dp(8)
        ):
            self._press_event.cancel()
            self._press_event = None
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self._press_event:
            self._press_event.cancel()
            self._press_event = None
        return super().on_touch_up(touch)

    def _copy(self) -> None:
        """长按 0.8 秒触发：整条文本复制到剪贴板。"""
        self._press_event = None
        try:
            Clipboard.copy(self.text_value)
        except Exception:
            pass


class ChatScreen(Screen):
    """对话页：气泡列表 + 输入框；内核计算放后台线程。"""

    module_title = StringProperty("对话")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._history: list[tuple[str, str]] = []  # (角色, 文本)

    def start_conversation(self, title: str) -> None:
        """从首页进来：只设模块标题、清空历史、输入框留空由用户自己描述。"""
        self.module_title = title
        self.ids.entry.text = ""          # 不预填示例问题
        self._history = []                # 不加欢迎气泡
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
        # B2 关键实体复述确认（G6：金额/日期/文号未确认不进结论）。
        # 只作提示气泡，不拦截、不改内核回答，避免破坏既有流程。
        try:
            recap = recap_question(detect_entities(text))
        except Exception:
            recap = ""
        if recap:
            self._history.append(("assistant", "【请核对】" + recap + " 如有误请改正后重发。"))
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

    def on_paste(self) -> None:
        """把系统剪贴板文字粘进输入框（长按输入框也可用系统粘贴）。"""
        try:
            text = Clipboard.paste()
        except Exception:
            text = ""
        if text:
            self.ids.entry.text = (self.ids.entry.text + text).strip()

    def on_upload(self) -> None:
        """
        调起系统选择器，只记录文件名，不读取内容、不做 OCR。
        Android 上系统选择是异步的：本函数立即返回，文件名稍后由回调给出。
        """
        started = attach_select_file(self._on_file_selected, file_type="any")
        if not started:
            self._history.append(("assistant",
                "【上传文件】当前环境不支持文件选择（降级模式），"
                "请先用文字描述材料内容。"))
            self._render_transcript()

    def _on_file_selected(self, filename: str) -> None:
        """系统选择器回调（可能不在主线程）：把文件名作为材料记录进对话。"""
        note = (f"【已选择材料】{filename}\n"
                "（已记录文件名；当前版本不读取文件内容，"
                "OCR 识别与文档解析为后续功能）")
        self._ui(self._append_material_note, note)

    def _append_material_note(self, note: str) -> None:
        self._history.append(("assistant", note))
        self._render_transcript()

    def on_document(self) -> None:
        """打开文书生成弹窗（D1：用户主动要求成文）。"""
        DocView().open()

    def on_ocr(self) -> None:
        """打开识图辅助弹窗（C 节规则层：手动录入 -> 结构化表，不读图）。"""
        OcrView().open()


# ---------------------------------------------------------------------------
# 识图辅助弹窗（C 节规则层：手动录入 -> 结构化表，不读图内容）
# ---------------------------------------------------------------------------

class OcrView(ModalView):
    """OCR 规则层界面：选材料类型 + 手动录入字段 -> 结构化表 + 证据要点，可复制。"""

    type_list = ListProperty(ocr_types())
    field_hint = StringProperty("")
    result_text = StringProperty("")
    degrade_hint = StringProperty(degrade_notice())

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.on_type_change(self.ids.doc_type.text)

    def on_type_change(self, doc_type: str) -> None:
        """切换材料类型时，列出该类应录入的字段，方便业主照着填。"""
        fields = OCR_SPECS.get(doc_type, [])
        self.field_hint = "应录入字段：" + "、".join(fields) if fields else ""

    def build(self) -> None:
        """把录入的文本整理成 C2 结构化表 + C5 证据诊断。"""
        doc_type = self.ids.doc_type.text
        provided = parse_manual_entry(self.ids.entry.text)
        if not provided:
            self.result_text = "还没有录入字段。请按上方清单，每行写「字段名：值」。"
            return
        table = render_material_table(doc_type, provided)
        report = (table + "\n\n" + evidence_tip(doc_type))
        self.result_text = report

    def copy_result(self) -> None:
        """把整理结果复制到系统剪贴板，供粘贴到聊天/文书使用。"""
        if not self.result_text:
            return
        try:
            Clipboard.copy(self.result_text)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 文书生成弹窗
# ---------------------------------------------------------------------------

class DocView(ModalView):
    """文书生成：字段齐全后调用 docgen，PC 出 docx、手机出模板。"""

    message = StringProperty("")

    def generate(self) -> None:
        from core.evidence import missing_doc_fields, next_missing_question
        doc_type = self.ids.doc_type.text.strip() or "文书"
        party = self.ids.party.text.strip()
        req = DocRequest(
            doc_type=doc_type,
            party=party or "（待填写）",
            sections=[
                ("事实", self.ids.fact.text.strip() or "（待补充）"),
                ("依据", self.ids.basis.text.strip() or "具体条款待核实"),
                ("请求", self.ids.request.text.strip() or "（待补充）"),
                ("时限", self.ids.deadline.text.strip() or "（待补充）"),
            ],
        )
        # D2 前置检查：收件方缺失先问，一次一个（不靠编造填满）
        if not party:
            self.message = next_missing_question({"收件方全称": "", "事由": "有", "落款人": "有"})
            return
        try:
            result = generate_doc(req)
            report = describe_doc(result)
        except Exception as e:
            self.message = f"生成失败：{e}"
            return
        # 结果写进对话，用户可直接看到文件名/路径；关闭弹窗
        app = App.get_running_app()
        if app and app.chat_screen:
            app.chat_screen._history.append(("assistant", report))
            if not result.generated:
                app.chat_screen._history.append(("assistant", result.text))
            app.chat_screen._render_transcript()
        self.message = ""
        self.dismiss()


# ---------------------------------------------------------------------------
# 设置弹窗
# ---------------------------------------------------------------------------

class SettingsView(ModalView):
    """设置弹窗：账号信息 + 模块说明 + 法规库更新 + 关于 + 隐私清除。"""

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

        app = self.app_ref
        uname = app.auth.username() if app else ""
        section("账号与安全", f"当前用户：{uname or '（未登录）'}\n"
                "本机账号仅作使用门槛，不上传对话内容。\n"
                "忘记密码无法找回，只能清除应用数据重置后重新注册。")
        section("模块说明", "A 财务核查 · B 物业合规 · C 规划违建 · D 行政程序\n"
                "E 证据固定 · F 沟通博弈 · 其他：不确定时帮你引导归类")
        section("能力状态", "文字咨询：可用 · 关键数字复述核对：已启用\n"
                "文书生成：可用（电脑出 Word，手机出可复制模板）\n"
                "识图辅助：可用（底栏「识图」，手动录入字段后整理成表并比对；不读取图片）\n"
                "语音转写、图片自动识别：后续功能，当前为降级模式，请用文字描述。\n"
                "全程本地处理，不上传你的音频、图片与文书。")

        if app:
            panel = UpdatePanel(manager=app.update_manager,
                                device_manager=app.device_manager,
                                app_version=APP_VERSION)
            host.add_widget(panel)

        tech = app.technical_status() if app else ""
        section("关于", f"业主维权AI助手 v{APP_VERSION}\n"
                "本地优先，法规库可离线更新。\n"
                f"{tech}\n"
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

        # 本地账号（用户名+密码，首次注册，之后登录）
        self.auth = LocalAuth(app_dir)

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

        # 账号页 + 首页 + 对话页（KV 里不能直接嵌 Screen，必须在代码里 add）
        root = ScreenManager()
        auth_screen = AuthScreen(name="auth")
        home = HomeScreen(name="home")
        chat = ChatScreen(name="chat")
        root.add_widget(auth_screen)
        root.add_widget(home)
        root.add_widget(chat)
        self.root_widget = root
        self.home_screen = home
        self.chat_screen = chat
        self.auth_screen = auth_screen

        Clock.schedule_once(lambda dt: self._show_first_screen(), 0.1)
        return root

    def _show_first_screen(self) -> None:
        """启动时先过账号：未注册进注册页，已注册进登录页。"""
        if self.auth.is_registered():
            self.auth_screen.prepare(register_mode=False,
                                     username=self.auth.username())
            self.root_widget.current = "auth"
        else:
            self.auth_screen.prepare(register_mode=True)
            self.root_widget.current = "auth"
        self.refresh_status()

    def reset_auth(self) -> None:
        """忘记密码的唯一出路：清除账号，回到注册页。"""
        self.auth.clear()
        self.auth_screen.prepare(register_mode=True)
        self.root_widget.current = "auth"

    def refresh_status(self) -> None:
        """首页状态行只显示用户看得懂的信息；技术细节移到设置-关于。"""
        stats = self.db.stats()
        count = stats["law_count"]
        if count:
            text = f"法规库 {count} 条（点右上角设置可检查更新）"
        else:
            text = "法规库 0 条（点右上角设置可更新，更新后回答会附法规依据）"
        self.home_screen.refresh_status(text)

    def technical_status(self) -> str:
        """技术细节（版本/设备号/下载后端），供设置-关于查看。"""
        stats = self.db.stats()
        updated = (stats.get("last_update_at") or "")[:16].replace("T", " ")
        return (f"法规库版本 v{stats['law_version']} · 更新于 {updated or '未更新'}\n"
                f"设备 {self.device_manager.short_id()} · 下载通道 {backend_name()}")

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
