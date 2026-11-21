# -*- coding: utf-8 -*-
"""
auth.py —— 本地用户名/密码认证（无服务器）

能力边界（务必如实告知用户，不要夸大）：
  * 密码用 pbkdf2_hmac-sha256 加随机盐存储，磁盘不含明文；
  * 这是"本机使用门槛"，不是安全边界：能物理接触设备的人仍可绕过/清除数据；
  * 忘记密码无法找回（无服务器、无邮箱），只能清除应用数据重置。

存储：app.user_data_dir / "auth.json"，内容 {username, salt, digest, iterations}。
"""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

ITERATIONS = 200_000          # pbkdf2 迭代次数，兼顾移动端速度与强度
AUTH_FILE = "auth.json"


class AuthError(Exception):
    """认证相关的可预期错误。"""


class LocalAuth:
    """本地账号管理：注册 / 校验 / 是否已注册 / 清除。"""

    def __init__(self, app_data_dir: Path):
        self.path = Path(app_data_dir) / AUTH_FILE

    # ---------- 状态 ----------
    def is_registered(self) -> bool:
        return self.path.exists()

    def username(self) -> str:
        data = self._load()
        return str(data.get("username", "")) if data else ""

    # ---------- 注册 ----------
    def register(self, username: str, password: str) -> None:
        username = username.strip()
        if not username:
            raise AuthError("用户名不能为空")
        if len(password) < 4:
            raise AuthError("密码至少 4 位")
        if self.is_registered():
            raise AuthError("账号已存在，不能重复注册")

        salt = secrets.token_hex(16)
        digest = self._digest(password, salt)
        self._save({
            "username": username,
            "salt": salt,
            "digest": digest,
            "iterations": ITERATIONS,
        })

    # ---------- 校验 ----------
    def verify(self, username: str, password: str) -> bool:
        data = self._load()
        if not data:
            return False
        if str(data.get("username", "")) != username.strip():
            return False
        salt = str(data.get("salt", ""))
        expect = str(data.get("digest", ""))
        if not salt or not expect:
            return False
        actual = self._digest(password, salt)
        # 定长比较，避免时序侧信道
        return secrets.compare_digest(actual, expect)

    # ---------- 内部 ----------
    def _digest(self, password: str, salt_hex: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            bytes.fromhex(salt_hex), ITERATIONS,
        ).hex()

    def _load(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self) -> None:
        """清除账号（忘记密码时的唯一出路：重置后重新注册）。"""
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="auth_test_"))
    a = LocalAuth(d)
    assert not a.is_registered()
    a.register("业主", "secret123")
    assert a.is_registered() and a.username() == "业主"
    assert a.verify("业主", "secret123") is True
    assert a.verify("业主", "wrong") is False
    text = a.path.read_text(encoding="utf-8")
    assert "secret123" not in text
    a.clear()
    assert not a.is_registered()
    print("AUTH_OK")
