# -*- coding: utf-8 -*-
"""
downloader.py —— 更新包下载器（带依赖降级）

策略（对应角色要求：requests 仅用于辅助下载法规更新包）：
  * 优先用 requests（流式下载 + 进度回调）。
  * requests 未安装时自动降级到标准库 urllib.request，功能等价。
  * 支持 http(s):// 与 file://（后者用于跨设备本地更新包 / 离线测试）。
  * 超时、重试、进度回调；下载到 .part 临时文件，成功后原子改名，
    避免中断留下半截包被误认为完整包。
"""

from __future__ import annotations

import shutil
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

try:
    import requests  # type: ignore
    _HAS_REQUESTS = True
except ImportError:
    requests = None  # type: ignore
    _HAS_REQUESTS = False

# 进度回调签名: (downloaded_bytes, total_bytes, percent) -> None
ProgressCb = Callable[[int, int, float], None]


@dataclass
class DownloadResult:
    path: Path
    backend: str          # requests | urllib
    total_bytes: int
    elapsed_seconds: float

    def to_dict(self) -> dict:
        return {
            "path": str(self.path), "backend": self.backend,
            "total_bytes": self.total_bytes,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }


def _noop(*args, **kwargs) -> None:
    pass


def backend_name() -> str:
    """当前环境的下载后端总览（供 UI/日志显示）。"""
    return "requests" if _HAS_REQUESTS else "urllib"


def use_requests_for(url: str) -> bool:
    """
    是否对该 URL 使用 requests。
    requests 不支持 file://，本地更新包/离线场景必须走 urllib，
    否则装了 requests 反而会让 file:// 下载抛 InvalidSchema。
    """
    return _HAS_REQUESTS and urlparse(url).scheme.lower() in ("http", "https")


def download(url: str, dest: Path, progress_cb: ProgressCb = _noop,
             timeout: int = 20, retries: int = 2) -> DownloadResult:
    """
    下载 url 到 dest。成功返回 DownloadResult，失败抛异常。
    progress_cb 在每块数据到达时调用（调用方负责线程切换，见 updater）。
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    started = time.time()

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if use_requests_for(url):
                total = _download_requests(url, part, progress_cb, timeout)
                backend = "requests"
            else:
                total = _download_urllib(url, part, progress_cb, timeout)
                backend = "urllib"
            # 下载完整才原子改名
            shutil.move(str(part), str(dest))
            return DownloadResult(
                path=dest, backend=backend, total_bytes=total,
                elapsed_seconds=time.time() - started,
            )
        except Exception as e:
            last_error = e
            if part.exists():
                part.unlink()
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"下载失败（已重试 {retries} 次）: {last_error}")


def _download_requests(url: str, part: Path, cb: ProgressCb, timeout: int) -> int:
    resp = requests.get(url, stream=True, timeout=timeout)  # type: ignore[union-attr]
    resp.raise_for_status()
    total = int(resp.headers.get("Content-Length", 0))
    done = 0
    with open(part, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                done += len(chunk)
                cb(done, total, (done / total * 100) if total else 0.0)
    resp.close()
    return done


def _download_urllib(url: str, part: Path, cb: ProgressCb, timeout: int) -> int:
    # file:// 也走 urllib，天然支持本地更新包
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        with open(part, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                cb(done, total, (done / total * 100) if total else 0.0)
    return done


def read_version_info(url: str, timeout: int = 10) -> dict:
    """
    读取版本清单 version.json（轻量探测，不下载整包）。
    同样支持 requests / urllib 降级。
    """
    import json
    if use_requests_for(url):
        resp = requests.get(url, timeout=timeout)  # type: ignore[union-attr]
        resp.raise_for_status()
        return json.loads(resp.text)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


if __name__ == "__main__":
    print("下载后端:", backend_name())
    # 用本地文件源测试（无需网络）
    src = Path(__file__).parent / "dist" / "version.json"
    if src.exists():
        print("版本清单:", read_version_info(src.as_uri()))
    else:
        print("（未找到 dist/version.json，先运行 tools/make_package.py）")
