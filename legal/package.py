# -*- coding: utf-8 -*-
"""
package.py —— 法规库更新包格式定义、打包/解包、完整性校验、版本与时限计算

更新包是一个 .zip 文件，内部结构：
    manifest.json     包清单（版本、生成时间、模式、条文文件哈希、时限等）
    laws.json         法规条文数组（UTF-8）
    CHANGELOG.txt     可选，人类可读的变更说明

安全与完整性：
    * manifest.json 内含 laws.json 的 SHA-256，防止条文被篡改。
    * 包本身（zip 文件）的 SHA-256 由下载器计算，用于校验下载完整性，
      并写入 update_history 留痕。
    * 解压时做路径穿越防护（拒绝 ../ 与绝对路径），避免恶意包写坏本地文件。

版本比较：支持 "主.次.修订" 语义化版本（如 2026.11.0），缺位按 0 处理。
时限计算：manifest 可带 generated_at 与 max_age_days，超过时限的包视为陈旧，
UI 应提示用户「有更新但包已过期，请重新获取」。
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from database import Law

MANIFEST_NAME = "manifest.json"
LAWS_NAME = "laws.json"
CHANGELOG_NAME = "CHANGELOG.txt"
MANIFEST_SCHEMA = "1"


# ---------------------------------------------------------------------------
# 版本比较
# ---------------------------------------------------------------------------

def parse_version(version: str) -> tuple[int, int, int]:
    """把 '2026.11' 解析成 (2026, 11, 0)；非法字符按 0 处理。"""
    parts = re.findall(r"\d+", str(version))
    nums = [int(p) for p in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return nums[0], nums[1], nums[2]


def version_gt(a: str, b: str) -> bool:
    """a 是否严格大于 b。"""
    return parse_version(a) > parse_version(b)


def version_ge(a: str, b: str) -> bool:
    return parse_version(a) >= parse_version(b)


def is_newer(remote: str, local: str) -> bool:
    """远端版本是否比本地新（供「检查更新」判断）。"""
    return version_gt(remote, local)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@dataclass
class Manifest:
    schema_version: str
    version: str
    generated_at: str
    mode: str                 # full | incremental
    law_count: int
    laws_file: str
    laws_sha256: str
    min_app_version: str = "1.0.0"
    max_age_days: int = 30    # 包时限：超过则视为陈旧
    changelog: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Manifest":
        allowed = set(Manifest.__dataclass_fields__.keys())  # type: ignore[attr-defined]
        return Manifest(**{k: v for k, v in d.items() if k in allowed})

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @staticmethod
    def from_json(text: str) -> "Manifest":
        return Manifest.from_dict(json.loads(text))

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """判断包是否超过时限（generated_at + max_age_days < now）。"""
        if self.max_age_days <= 0:
            return False
        try:
            gen = datetime.fromisoformat(self.generated_at)
            if gen.tzinfo is None:
                gen = gen.replace(tzinfo=timezone.utc)
            now = now or datetime.now(timezone.utc)
            return gen + timedelta(days=self.max_age_days) < now
        except Exception:
            return False

    def app_compatible(self, app_version: str) -> bool:
        """当前 App 版本是否满足包的最低版本要求。"""
        return version_ge(app_version, self.min_app_version)


# ---------------------------------------------------------------------------
# 哈希工具
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def law_content_hash(law: Law) -> str:
    """条文正文哈希（用于增量比对，避免重复写入）。"""
    return sha256_bytes(law.content.encode("utf-8"))


# ---------------------------------------------------------------------------
# 打包
# ---------------------------------------------------------------------------

def build_package(out_path, laws: Iterable[Law], version: str,
                  mode: str = "full", max_age_days: int = 30,
                  changelog: str = "", min_app_version: str = "1.0.0") -> Path:
    """
    生成一个更新包 zip。返回包路径。
    调用方通常是法规库维护端（tools/make_package.py），不在 App 运行时执行。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    laws = list(laws)

    # 为每条条文计算内容哈希（若未提供）
    for law in laws:
        if not law.content_hash:
            law.content_hash = law_content_hash(law)

    laws_json = json.dumps([law.to_dict() for law in laws],
                           ensure_ascii=False, indent=2).encode("utf-8")
    manifest = Manifest(
        schema_version=MANIFEST_SCHEMA,
        version=version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        mode=mode if mode in ("full", "incremental") else "full",
        law_count=len(laws),
        laws_file=LAWS_NAME,
        laws_sha256=sha256_bytes(laws_json),
        min_app_version=min_app_version,
        max_age_days=max_age_days,
        changelog=changelog,
    )

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, manifest.to_json().encode("utf-8"))
        zf.writestr(LAWS_NAME, laws_json)
        if changelog:
            zf.writestr(CHANGELOG_NAME, changelog.encode("utf-8"))
    return out_path


# ---------------------------------------------------------------------------
# 解包与校验
# ---------------------------------------------------------------------------

@dataclass
class UnpackedPackage:
    """解包结果：manifest、条文列表、包 sha256、临时目录。"""
    manifest: Manifest
    laws: list[Law]
    package_sha256: str
    work_dir: Path

    def to_dict(self) -> dict:
        return {
            "manifest": self.manifest.to_dict(),
            "law_count": len(self.laws),
            "package_sha256": self.package_sha256,
            "work_dir": str(self.work_dir),
        }


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    """安全解压：拒绝路径穿越与绝对路径。"""
    target = target.resolve()
    for member in zf.infolist():
        name = member.filename
        if name.startswith("/") or name.startswith("\\") or ".." in Path(name).parts:
            raise ValueError(f"更新包含非法路径，已拒绝: {name}")
    zf.extractall(target)


def unpack_and_verify(package_path, work_dir, package_sha256: Optional[str] = None,
                      max_age_days: Optional[int] = None) -> UnpackedPackage:
    """
    解包并做完整性校验。任一步失败抛异常（由上层 updater 捕获并记 failed）。
      - package_sha256：若提供，先校验整包哈希（下载完整性）。
      - manifest.laws_sha256：校验条文文件哈希（防篡改）。
      - max_age_days：可覆盖包内时限（None 时用包内值）。
    """
    package_path = Path(package_path)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    actual_pkg_hash = sha256_file(package_path)
    if package_sha256 and actual_pkg_hash.lower() != package_sha256.lower():
        raise ValueError("整包 SHA-256 校验失败：下载可能不完整或被篡改")

    with zipfile.ZipFile(package_path, "r") as zf:
        _safe_extract(zf, work_dir)

    manifest_path = work_dir / MANIFEST_NAME
    if not manifest_path.exists():
        raise ValueError(f"更新包缺少 {MANIFEST_NAME}")
    manifest = Manifest.from_json(manifest_path.read_text(encoding="utf-8"))

    if manifest.schema_version != MANIFEST_SCHEMA:
        raise ValueError(f"不支持的 manifest 版本: {manifest.schema_version}")

    if max_age_days is not None:
        manifest.max_age_days = max_age_days
    if manifest.is_expired():
        raise ValueError("更新包已超过有效时限，请重新获取最新版本")

    laws_path = work_dir / manifest.laws_file
    if not laws_path.exists():
        raise ValueError(f"更新包缺少条文文件: {manifest.laws_file}")
    laws_bytes = laws_path.read_bytes()
    if sha256_bytes(laws_bytes).lower() != manifest.laws_sha256.lower():
        raise ValueError("条文文件 SHA-256 校验失败：内容可能被篡改")

    raw_laws = json.loads(laws_bytes.decode("utf-8"))
    laws = [Law.from_dict(d) for d in raw_laws]
    if len(laws) != manifest.law_count:
        raise ValueError(f"条文数量不符：清单声明 {manifest.law_count}，实际 {len(laws)}")

    return UnpackedPackage(
        manifest=manifest, laws=laws,
        package_sha256=actual_pkg_hash, work_dir=work_dir,
    )


if __name__ == "__main__":
    import tempfile
    base = Path(tempfile.mkdtemp(prefix="pkg_selftest_"))
    laws = [
        Law("mfd-238", "中华人民共和国民法典", "物权编", "第二百三十八条", "C",
            "侵害物权，造成权利人损害的，权利人可以依法请求损害赔偿。", "物权 损害赔偿"),
        Law("wygl-11", "物业管理条例", "", "第十一条", "B",
            "下列事项由业主共同决定：制定和修改业主大会议事规则。", "业主共同决定"),
    ]
    pkg = build_package(base / "laws_2026.11.0.zip", laws, "2026.11.0",
                        changelog="新增物业服务合同相关条文")
    print("生成包:", pkg.name, "| 包哈希:", sha256_file(pkg)[:16])
    unpacked = unpack_and_verify(pkg, base / "unpack")
    print("解包版本:", unpacked.manifest.version, "| 条文数:", len(unpacked.laws),
          "| 过期:", unpacked.manifest.is_expired())
    print("版本比较 2026.11.1 > 2026.11.0 :", is_newer("2026.11.1", "2026.11.0"))
    # 篡改测试
    laws[0].content = "被篡改的内容"
    bad = build_package(base / "bad.zip", laws, "2026.11.1")
    with zipfile.ZipFile(bad, "a") as zf:
        zf.writestr(LAWS_NAME, json.dumps([l.to_dict() for l in laws], ensure_ascii=False))
    try:
        unpack_and_verify(bad, base / "bad_unpack")
        print("篡改测试: 未检出（异常！）")
    except ValueError as e:
        print("篡改测试: 正确拒绝 ->", str(e)[:30])
