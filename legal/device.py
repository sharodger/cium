# -*- coding: utf-8 -*-
"""
device.py —— 设备环境自动检测 + 设备唯一标识生成

设计要点（对应系统提示词第十节「软件运行与跨设备部署」）：
  1. 首次在新设备打开：检测设备环境、读取设备唯一标识、重新初始化本地存储空间，
     并提示用户进行设备绑定或身份验证。
  2. 设备唯一标识：先取硬件 ID，再用 hashlib 哈希（不可反推原始硬件信息，保护隐私）。
  3. 跨端差异：PC（Windows/Linux/macOS）与 Android 走不同的硬件 ID 获取路径；
     Android 侧用 Pyjnius 桥接系统 API 读取 ANDROID_ID / IMEI，但不用于语音识别。
  4. 全部获取方式均带降级链，任何一端失败都不会导致应用无法启动。

本模块只依赖标准库；Pyjnius 只在 Android 且已安装时才导入。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 平台判定
# ---------------------------------------------------------------------------

def is_android() -> bool:
    """是否为 Android 运行环境（Kivy / p4a 环境下 sys.platform == 'android'）。"""
    return sys.platform == "android" or "android" in platform.platform().lower()


def is_ios() -> bool:
    """是否为 iOS 运行环境（kivy-ios 下 sys.platform 为 'ios' 或 'darwin' 且特定标记）。"""
    return sys.platform == "ios" or os.environ.get("KIVY_IOS") == "1"


def platform_name() -> str:
    """返回归一化平台名：android / ios / windows / linux / macos / unknown。"""
    if is_android():
        return "android"
    if is_ios():
        return "ios"
    sysname = platform.system().lower()
    return {
        "windows": "windows",
        "linux": "linux",
        "darwin": "macos",
    }.get(sysname, "unknown")


@dataclass
class DeviceProfile:
    """设备画像：应用初始化时写入本地配置，供 UI 顶部状态栏与绑定流程使用。"""
    device_id: str            # 哈希后的唯一标识（对外展示用短哈希）
    raw_source: str           # 硬件 ID 来源标记（如 wmic / ANDROID_ID / uuid-fallback），不含原始值
    platform: str
    os_release: str
    machine: str
    app_data_dir: str
    first_seen: str           # ISO8601，首次初始化时间
    last_seen: str
    bound: bool = False       # 是否已完成设备绑定/身份验证
    bound_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DeviceProfile":
        return cls(**d)


# ---------------------------------------------------------------------------
# 硬件 ID 采集（原始值仅在内存中使用，绝不落盘）
# ---------------------------------------------------------------------------

def _read_windows_uuid() -> Optional[str]:
    """
    Windows：读注册表 MachineGuid。
    纯 winreg 实现，不启动任何子进程，避免被安全策略/黑名单拦截。
    """
    try:
        import winreg  # type: ignore
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
        finally:
            winreg.CloseKey(key)
        return value or None
    except Exception:
        return None


def _read_linux_uuid() -> Optional[str]:
    """Linux：读 DMI product_uuid 或 /etc/machine-id。"""
    for p in ("/sys/class/dmi/id/product_uuid", "/etc/machine-id"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                value = f.read().strip()
                if value:
                    return value
        except Exception:
            continue
    return None


def _read_macos_uuid() -> Optional[str]:
    """macOS：IOPlatformUUID。"""
    try:
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            stderr=subprocess.DEVNULL,
            timeout=4,
        ).decode("utf-8", "ignore")
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return None


def _read_android_id() -> Optional[str]:
    """
    Android：通过 Pyjnius 读 Settings.Secure.ANDROID_ID。
    仅用于生成设备唯一标识，不用于语音识别（语音走 Vosk 本地方案）。
    """
    if not is_android():
        return None
    try:
        from jnius import autoclass  # type: ignore
        Secure = autoclass("android.provider.Settings$Secure")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        ctx = PythonActivity.mActivity
        return Secure.getString(ctx.getContentResolver(), Secure.ANDROID_ID)
    except Exception:
        return None


def _fallback_uuid() -> str:
    """最终降级：随机 UUID（跨设备复制时会变化，触发重新绑定，符合预期）。"""
    return str(uuid.uuid4())


def collect_raw_hardware_id() -> tuple[str, str]:
    """
    返回 (原始硬件ID, 来源标记)。原始值只在内存中参与哈希，绝不写入文件/日志。
    """
    p = platform_name()
    getters = []
    if p == "android":
        getters = [("ANDROID_ID", _read_android_id)]
    elif p == "windows":
        getters = [("machine-uuid", _read_windows_uuid)]
    elif p == "linux":
        getters = [("dmi/machine-id", _read_linux_uuid)]
    elif p == "macos":
        getters = [("IOPlatformUUID", _read_macos_uuid)]

    for source, fn in getters:
        try:
            value = fn()
            if value:
                return str(value), source
        except Exception:
            continue
    return _fallback_uuid(), "uuid-fallback"


def hash_device_id(raw_value: str, salt: str = "owner-rights-ai-assistant") -> str:
    """对硬件 ID 做加盐 SHA-256，输出 32 位短哈希（抗碰撞且不可反推）。"""
    digest = hashlib.sha256((salt + "|" + raw_value).encode("utf-8")).hexdigest()
    return digest[:32]


# ---------------------------------------------------------------------------
# 应用数据目录
# ---------------------------------------------------------------------------

def default_app_data_dir(app_name: str = "业主维权AI助手") -> Path:
    """按平台返回应用私有数据目录；Android 用 Kivy 的 user_data_dir。"""
    if is_android() or is_ios():
        try:
            from kivy.utils import platform as kivy_platform  # type: ignore
            from kivy.app import App  # type: ignore
            base = Path(App.get_running_app().user_data_dir)
            return base
        except Exception:
            return Path(".") / app_name
    p = platform_name()
    home = Path.home()
    if p == "windows":
        base = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    elif p == "macos":
        base = home / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
    target = base / app_name
    target.mkdir(parents=True, exist_ok=True)
    return target


# ---------------------------------------------------------------------------
# 设备画像持久化（跨设备复制检测）
# ---------------------------------------------------------------------------

class DeviceManager:
    """
    管理设备画像的生命周期。
    - 首次运行：采集硬件 ID → 哈希 → 建画像 → 落盘 → bound=False（提示绑定）。
    - 再次运行：比对当前哈希与落盘哈希；不一致说明被复制到新设备 →
      重新初始化存储空间并重置 bound=False。
    """

    PROFILE_FILE = "device_profile.json"

    def __init__(self, app_data_dir: Optional[Path] = None):
        self.app_data_dir = Path(app_data_dir) if app_data_dir else default_app_data_dir()
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path = self.app_data_dir / self.PROFILE_FILE

    def current_hashed_id(self) -> tuple[str, str]:
        raw, source = collect_raw_hardware_id()
        return hash_device_id(raw), source

    def load_profile(self) -> Optional[DeviceProfile]:
        if not self.profile_path.exists():
            return None
        try:
            with open(self.profile_path, "r", encoding="utf-8") as f:
                return DeviceProfile.from_dict(json.load(f))
        except Exception:
            return None

    def save_profile(self, profile: DeviceProfile) -> None:
        tmp = self.profile_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.profile_path)  # 原子替换，避免写一半损坏

    def initialize(self) -> tuple[DeviceProfile, bool]:
        """
        返回 (画像, 是否为新设备/需重新绑定)。
        这是应用启动流程的第一步，UI 顶部状态栏据此显示「设备识别状态」。
        """
        now = datetime.now(timezone.utc).isoformat()
        hashed, source = self.current_hashed_id()
        existing = self.load_profile()

        if existing and existing.device_id == hashed:
            # 同一台设备：更新 last_seen，保持绑定状态
            existing.last_seen = now
            self.save_profile(existing)
            return existing, False

        # 新设备（首次安装 或 跨设备复制）：重建画像
        profile = DeviceProfile(
            device_id=hashed,
            raw_source=source,
            platform=platform_name(),
            os_release=platform.release(),
            machine=platform.machine(),
            app_data_dir=str(self.app_data_dir),
            first_seen=now,
            last_seen=now,
            bound=False,
        )
        self.save_profile(profile)
        return profile, True

    def bind(self, token_hash: Optional[str] = None) -> DeviceProfile:
        """完成设备绑定/身份验证。token_hash 为可选口令的哈希，不存明文。"""
        profile = self.load_profile()
        if profile is None:
            profile, _ = self.initialize()
        profile.bound = True
        profile.bound_at = datetime.now(timezone.utc).isoformat()
        # 若提供了口令哈希，附加字段保存（不落明文）
        if token_hash:
            data = profile.to_dict()
            data["binding_token_hash"] = token_hash
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            self.save_profile(profile)
        return profile

    def short_id(self, profile: Optional[DeviceProfile] = None) -> str:
        """供 UI 展示的短标识，如 DEV-A1B2C3D4。"""
        p = profile or self.load_profile()
        if not p:
            return "DEV-UNKNOWN"
        return "DEV-" + p.device_id[-8:].upper()


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    dm = DeviceManager(app_data_dir=Path("./_selftest_device"))
    profile, is_new = dm.initialize()
    print("平台:", profile.platform, "| 设备标识:", dm.short_id(profile))
    print("来源标记:", profile.raw_source, "| 新设备:", is_new, "| 已绑定:", profile.bound)
    profile2, is_new2 = dm.initialize()
    print("二次启动 -> 新设备:", is_new2, "（应为 False）")
    dm.bind()
    print("绑定后 -> 已绑定:", dm.load_profile().bound)
