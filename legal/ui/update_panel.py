# -*- coding: utf-8 -*-
"""
update_panel.py —— 法规库更新设置面板（Kivy）

放进 App 右上角「设置框」的一个 tab / 弹出层：
  * 顶部状态栏数据：本地版本、法规条数、网络状态、设备标识
  * 按钮：检查更新 / 下载并应用 / 查看历史 / 回滚
  * 进度条 + 日志区，实时显示更新流水线状态

线程模型（关键）：
  Kivy 的 UI 只能在主线程改。检查/下载/校验/入库全部在后台线程执行，
  通过 _ui_call() 把回调排到主线程 Clock 队列。绝不从后台线程直接碰控件。

无 Kivy 环境下本模块仍可 import（KV 字符串与类定义分离），便于内核自测。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 既可作包导入（legal_repo.ui.update_panel），也可独立脚本运行
_PARENT = str(Path(__file__).resolve().parent.parent)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

try:
    from kivy.clock import Clock
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.progressbar import ProgressBar
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.textinput import TextInput
    from kivy.properties import StringProperty, NumericProperty
    _HAS_KIVY = True
except ImportError:
    _HAS_KIVY = False
    # 提供桩类，保证无 Kivy 时 import 不报错
    class BoxLayout:  # type: ignore
        def __init__(self, *a, **k): pass
    class _Stub:
        def __init__(self, *a, **k): pass
    Button = Label = ProgressBar = ScrollView = TextInput = _Stub  # type: ignore
    class StringProperty:  # type: ignore
        def __init__(self, *a, **k): pass
    class NumericProperty:  # type: ignore
        def __init__(self, *a, **k): pass
    class _Clock:
        @staticmethod
        def schedule_once(fn, timeout=0):
            fn(0)
    Clock = _Clock()  # type: ignore

from device import DeviceManager
from updater import LegalUpdateManager, UpdatePlan, UpdateStatus, UpdateError

if _HAS_KIVY:
    from kivy.lang import Builder

    KV = r"""
<UpdatePanel>:
    orientation: 'vertical'
    padding: 12
    spacing: 8

    BoxLayout:
        size_hint_y: None
        height: 44
        Label:
            text: '法规库版本更新'
            font_size: '20sp'
            bold: True
        Label:
            text: root.device_label
            font_size: '12sp'
            halign: 'right'

    BoxLayout:
        size_hint_y: None
        height: 30
        Label:
            text: root.version_label
            font_size: '14sp'
        Label:
            text: root.network_label
            font_size: '12sp'
            halign: 'right'

    ProgressBar:
        id: progress
        max: 100
        value: root.progress_value

    Label:
        id: status
        text: root.status_text
        size_hint_y: None
        height: 28
        font_size: '13sp'

    ScrollView:
        size_hint_y: 1
        TextInput:
            id: log
            readonly: True
            multiline: True
            font_size: '12sp'
            text: root.log_text
            background_color: 0.98, 0.98, 0.98, 1

    BoxLayout:
        size_hint_y: None
        height: 48
        spacing: 6
        Button:
            text: '检查更新'
            on_press: root.check_update()
        Button:
            text: '下载并应用'
            on_press: root.download_and_apply()
        Button:
            text: '回滚'
            on_press: root.rollback()
    """
    Builder.load_string(KV)


class UpdatePanel(BoxLayout):
    """法规库更新面板。由 App 的设置入口实例化并传入依赖。"""

    if _HAS_KIVY:
        version_label = StringProperty("本地版本：-")
        device_label = StringProperty("设备：-")
        network_label = StringProperty("网络：-")
        status_text = StringProperty("就绪")
        log_text = StringProperty("")
        progress_value = NumericProperty(0)

    def __init__(self, manager: LegalUpdateManager,
                 device_manager: DeviceManager,
                 app_version: str = "1.0.0", **kwargs):
        super().__init__(**kwargs)
        self.manager = manager
        self.device_manager = device_manager
        self.app_version = app_version
        self._plan: UpdatePlan | None = None
        self._busy = False
        self._log_lines: list[str] = []
        self._refresh_device()
        self._refresh_version()

    # ---------------- 主线程调度桥 ----------------
    def _ui_call(self, fn, *args, **kwargs) -> None:
        """把任意回调排到主线程执行（Kivy Clock）；无 Clock 时直接执行。"""
        Clock.schedule_once(lambda dt: fn(*args, **kwargs), 0)

    # ---------------- 显示更新 ----------------
    def _append_log(self, line: str) -> None:
        self._log_lines.append(line)
        if len(self._log_lines) > 200:
            self._log_lines = self._log_lines[-200:]
        self._ui_call(self._set_log_text, "\n".join(self._log_lines))

    def _set_log_text(self, text: str) -> None:
        self.log_text = text
        # 自动滚到底部
        try:
            log = self.ids.log
            log.cursor = (0, len(text))
        except Exception:
            pass

    def _refresh_device(self) -> None:
        profile = self.device_manager.load_profile() or self.device_manager.initialize()[0]
        self.device_label = self.device_manager.short_id(profile)

    def _refresh_version(self) -> None:
        stats = self.manager.db.stats()
        self.version_label = (f"本地版本：v{stats['law_version']} · "
                              f"{stats['law_count']} 条条文")

    def _on_status(self, status: UpdateStatus, msg: str) -> None:
        """来自后台线程的回调 -> 排到主线程更新 UI。"""
        self._ui_call(self._apply_status, status, msg)

    def _apply_status(self, status: UpdateStatus, msg: str) -> None:
        self.status_text = msg
        self._append_log(f"[{status.value}] {msg}")
        if status in (UpdateStatus.SUCCESS, UpdateStatus.FAILED,
                      UpdateStatus.UP_TO_DATE, UpdateStatus.ROLLED_BACK):
            self._busy = False
            if status in (UpdateStatus.SUCCESS, UpdateStatus.ROLLED_BACK):
                self._refresh_version()
        if status == UpdateStatus.VERIFYING:
            self.progress_value = 100

    def _on_progress(self, done: int, total: int, pct: float) -> None:
        # 下载阶段 0->90%，校验与入库占用剩余区间，视觉更连贯
        self._ui_call(self._set_progress, pct * 0.9)

    def _set_progress(self, value: float) -> None:
        self.progress_value = min(100, max(0, value))

    # ---------------- 按钮动作（后台线程执行耗时操作） ----------------
    def check_update(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._set_progress(0)
        self._append_log("— 开始检查更新 —")

        def work():
            try:
                plan = self.manager.check_for_update()
                self._plan = plan
                self._ui_call(self._show_plan, plan)
            except UpdateError as e:
                self._on_status(e.stage, e.message)
            except Exception as e:
                self._on_status(UpdateStatus.FAILED, f"检查失败：{e}")

        self._spawn(work)

    def _show_plan(self, plan: UpdatePlan) -> None:
        self.status_text = plan.detail
        if not plan.compatible:
            self._append_log(f"！更新包需要 App ≥ {plan.min_app_version}")
        self._busy = False

    def download_and_apply(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._set_progress(0)

        def work():
            try:
                plan = self._plan
                if plan is None or not plan.has_update:
                    plan = self.manager.check_for_update()
                    self._plan = plan
                if not plan.has_update:
                    self._on_status(UpdateStatus.UP_TO_DATE, "已是最新版本，无需下载")
                    return
                self.manager.apply_update(plan)
            except UpdateError as e:
                self._on_status(e.stage, e.message)
            except Exception as e:
                self._on_status(UpdateStatus.FAILED, f"更新失败：{e}")

        self._spawn(work)

    def rollback(self) -> None:
        if self._busy:
            return
        self._busy = True

        def work():
            try:
                ok = self.manager.rollback()
                if ok:
                    self._on_status(UpdateStatus.ROLLED_BACK, "已回滚到上一版本")
                else:
                    self._on_status(UpdateStatus.FAILED, "没有可回滚的备份")
            except Exception as e:
                self._on_status(UpdateStatus.FAILED, f"回滚失败：{e}")

        self._spawn(work)

    def _spawn(self, work) -> None:
        """统一后台线程入口（daemon，避免退出时阻塞）。"""
        import threading
        # 更新引擎本身通过构造时的 status_cb/progress_cb 回传状态
        self.manager.status_cb = self._on_status
        self.manager.progress_cb = self._on_progress
        t = threading.Thread(target=work, daemon=True, name="legal-update")
        t.start()


# ---------------------------------------------------------------------------
# 无 Kivy 环境下的逻辑自测：用假 Clock（立即执行）验证回调链不崩
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    base = Path(tempfile.mkdtemp(prefix="panel_test_"))
    from database import LegalDatabase
    db = LegalDatabase(base / "legal.db")
    dist = Path(__file__).resolve().parent.parent / "dist"
    mgr = LegalUpdateManager(db, base, (dist / "version.json").as_uri(), dist.as_uri())
    dm = DeviceManager(app_data_dir=base)
    panel = UpdatePanel(manager=mgr, device_manager=dm)
    print("面板初始化 OK | 设备:", panel.device_label, "| 版本:", panel.version_label)
    # 直接调引擎，验证状态回调接线
    mgr.status_cb = panel._on_status
    plan = mgr.check_for_update()
    print("检查更新:", plan.detail)
