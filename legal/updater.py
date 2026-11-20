# -*- coding: utf-8 -*-
"""
updater.py —— 法规库版本更新引擎（编排核心）

完整流水线（对应系统提示词第六节 / 第十节）：
    1. check_for_update()  读取 version.json 轻量探测，与本地版本比较
    2. download()          下载更新包（requests/urllib 降级），进度回调
    3. verify & unpack()   双层 SHA-256 校验 + 安全解压 + 时限检查
    4. backup()            SQLite 一致性备份旧库（供回滚）
    5. apply()             事务化整库替换/增量合并 + 版本切换
    6. 失败处理            任一环节失败 -> 回滚备份 -> 记 failed 历史 -> 抛出 UpdateError

状态机 UpdateStatus 供 Kivy UI 显示当前进度；所有耗时操作由调用方放到后台线程，
通过 status_cb(状态, 消息) 回调，UI 侧再用 Clock.schedule_once 回主线程渲染。
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Callable

from database import LegalDatabase
from downloader import backend_name, download, read_version_info
from package import (
    UnpackedPackage, is_newer, unpack_and_verify, version_ge,
)

# 状态回调签名: (UpdateStatus, message) -> None
StatusCb = Callable[["UpdateStatus", str], None]


class UpdateStatus(str, Enum):
    IDLE = "idle"
    CHECKING = "checking"
    UPDATE_AVAILABLE = "update_available"
    UP_TO_DATE = "up_to_date"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    APPLYING = "applying"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class UpdateError(Exception):
    """更新流程中可预期的失败，携带发生阶段。"""
    def __init__(self, stage: UpdateStatus, message: str):
        super().__init__(message)
        self.stage = stage
        self.message = message


@dataclass
class UpdatePlan:
    """检查结果：是否要更新、目标版本、包地址、清单信息。"""
    has_update: bool
    local_version: str
    remote_version: str
    package_url: str = ""
    package_sha256: str = ""
    law_count: int = 0
    min_app_version: str = "1.0.0"
    compatible: bool = True
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class LegalUpdateManager:
    """更新引擎门面。一个 App 实例持有一个。"""

    BACKUP_PREFIX = "legal_backup_"

    def __init__(self, db: LegalDatabase, app_data_dir: Path,
                 version_url: str, package_base_url: str,
                 app_version: str = "1.0.0",
                 status_cb: StatusCb | None = None,
                 progress_cb: Callable[[int, int, float], None] | None = None):
        self.db = db
        self.app_data_dir = Path(app_data_dir)
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.version_url = version_url
        self.package_base_url = package_base_url.rstrip("/")
        self.app_version = app_version
        self.status_cb = status_cb or (lambda *_: None)
        self.progress_cb = progress_cb or (lambda *_: None)
        self.work_dir = Path(tempfile.gettempdir()) / "owner_rights_update"
        self.backup_dir = self.app_data_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _emit(self, status: UpdateStatus, msg: str) -> None:
        self.status_cb(status, msg)

    # ---------------- 1. 检查更新 ----------------
    def check_for_update(self) -> UpdatePlan:
        """轻量探测远端版本，与本地比较。不下载整包。"""
        self._emit(UpdateStatus.CHECKING, "正在检查法规库版本…")
        try:
            info = read_version_info(self.version_url)
        except Exception as e:
            raise UpdateError(UpdateStatus.CHECKING, f"检查更新失败：{e}")

        remote = str(info.get("version", "0.0.0"))
        local = self.db.law_version
        package_name = str(info.get("package", ""))
        package_url = (
            info.get("package_url") or f"{self.package_base_url}/{package_name}"
        )
        min_app = str(info.get("min_app_version", "1.0.0"))
        compatible = version_ge(self.app_version, min_app)
        sha = str(info.get("sha256", ""))
        count = int(info.get("law_count", 0))

        has_update = is_newer(remote, local)
        if has_update:
            detail = f"发现新版本 {remote}（本地 {local}）"
            self._emit(UpdateStatus.UPDATE_AVAILABLE, detail)
        else:
            detail = f"已是最新版本 {local}"
            self._emit(UpdateStatus.UP_TO_DATE, detail)

        return UpdatePlan(
            has_update=has_update, local_version=local, remote_version=remote,
            package_url=package_url, package_sha256=sha, law_count=count,
            min_app_version=min_app, compatible=compatible, detail=detail,
        )

    # ---------------- 2~5. 执行更新 ----------------
    def apply_update(self, plan: UpdatePlan, mode: str | None = None) -> UnpackedPackage:
        """
        按计划执行完整更新流水线。同步方法，调用方应放到后台线程。
        成功返回解包结果；失败抛 UpdateError 且已自动回滚。
        """
        if not plan.has_update:
            raise UpdateError(UpdateStatus.CHECKING, "没有可用更新")
        if not plan.compatible:
            raise UpdateError(
                UpdateStatus.CHECKING,
                f"更新包需要 App 版本 ≥ {plan.min_app_version}，当前 {self.app_version}",
            )

        backup_path = self.backup_dir / f"{self.BACKUP_PREFIX}{self.db.law_version}.db"
        work = self.work_dir / f"pkg_{plan.remote_version}"
        pkg_path = self.work_dir / f"laws_{plan.remote_version}.zip"
        backed_up = False

        # 清理旧的临时工作目录，避免残留文件干扰校验
        if work.exists():
            shutil.rmtree(work)

        try:
            # --- 下载 ---
            self._emit(UpdateStatus.DOWNLOADING, f"正在下载法规库 {plan.remote_version}…")
            try:
                dl = download(plan.package_url, pkg_path, progress_cb=self.progress_cb)
            except Exception as dl_err:
                raise UpdateError(UpdateStatus.DOWNLOADING, str(dl_err))
            self._emit(UpdateStatus.DOWNLOADING,
                       f"下载完成（{dl.backend}，{dl.total_bytes // 1024} KB）")

            # --- 校验 + 解包 ---
            self._emit(UpdateStatus.VERIFYING, "正在校验更新包完整性…")
            try:
                unpacked = unpack_and_verify(
                    pkg_path, work,
                    package_sha256=plan.package_sha256 or None,
                )
            except ValueError as ve:
                raise UpdateError(UpdateStatus.VERIFYING, str(ve))
            use_mode = mode or unpacked.manifest.mode

            # --- 备份旧库 ---
            self.db.backup_to(backup_path)
            backed_up = True

            # --- 入库 + 版本切换（事务化） ---
            self._emit(UpdateStatus.APPLYING, "正在写入法规库…")
            try:
                self.db.replace_all(
                    unpacked.laws,
                    new_version=unpacked.manifest.version,
                    package_sha256=unpacked.package_sha256,
                    mode=use_mode,
                )
            except Exception as db_err:
                raise UpdateError(UpdateStatus.APPLYING, f"写入数据库失败：{db_err}")

            self._emit(UpdateStatus.SUCCESS,
                       f"法规库已更新至 {unpacked.manifest.version}"
                       f"（{len(unpacked.laws)} 条）")
            return unpacked

        except Exception as e:
            err = e if isinstance(e, UpdateError) else UpdateError(
                UpdateStatus.FAILED, str(e)
            )
            self.db.record_failed_update(
                plan.remote_version, plan.package_sha256, f"{err.stage.value}: {err.message}"
            )
            # 回滚：若已备份且新版本已部分写入，恢复备份
            if backed_up and self.db.law_version == plan.remote_version:
                try:
                    self.rollback(backup_path)
                    self._emit(UpdateStatus.ROLLED_BACK, "更新失败，已回滚到旧版本")
                except Exception as rb_err:
                    self._emit(UpdateStatus.FAILED, f"回滚也失败：{rb_err}")
            self._emit(UpdateStatus.FAILED, err.message)
            raise err

    # ---------------- 回滚 ----------------
    def rollback(self, backup_path: Path | None = None) -> bool:
        """
        从备份恢复法规库。不指定路径时自动选最近的备份。
        用 SQLite backup API 把备份写回主库：全程走数据库引擎，自动处理 WAL，
        不直接删 WAL/SHM 文件（那样可能丢失未 checkpoint 的数据或触发文件占用）。
        """
        import sqlite3
        if backup_path is None:
            candidates = sorted(
                self.backup_dir.glob(f"{self.BACKUP_PREFIX}*.db"),
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            if not candidates:
                return False
            backup_path = candidates[0]
        backup_path = Path(backup_path)
        if not backup_path.exists():
            return False

        src = sqlite3.connect(str(backup_path))
        dst = sqlite3.connect(str(self.db.db_path))
        try:
            src.backup(dst)   # 把备份内容整体写回主库，引擎负责一致性
        finally:
            src.close()
            dst.close()
        self._emit(UpdateStatus.ROLLED_BACK, f"已从 {backup_path.name} 恢复")
        return True

    # ---------------- 一键更新（检查+执行） ----------------
    def update_all(self, mode: str | None = None) -> UpdatePlan:
        plan = self.check_for_update()
        if plan.has_update:
            self.apply_update(plan, mode=mode)
        return plan


if __name__ == "__main__":
    import tempfile
    base = Path(tempfile.mkdtemp(prefix="updater_selftest_"))
    db_path = base / "legal.db"
    db = LegalDatabase(db_path)
    print("初始版本:", db.law_version, "| 后端:", backend_name())

    dist = Path(__file__).parent / "dist"
    version_url = (dist / "version.json").as_uri()

    def on_status(status, msg):
        print(f"  [{status.value}] {msg}")

    def on_progress(done, total, pct):
        if pct >= 100 or int(pct) % 25 == 0:
            print(f"  进度: {done}/{total} ({pct:.0f}%)")

    mgr = LegalUpdateManager(
        db, base, version_url, dist.as_uri(),
        status_cb=on_status, progress_cb=on_progress,
    )
    plan = mgr.check_for_update()
    print("检查结果:", plan.to_dict())
    if plan.has_update:
        mgr.apply_update(plan)
        print("更新后版本:", db.law_version, "| 条文数:", db.law_count)
        print("检索'公共收益':", [l.law_id for l in db.search("公共收益")])
        print("更新历史:", [(r.version, r.status) for r in db.update_history()])
