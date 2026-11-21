# -*- coding: utf-8 -*-
"""
attach.py —— 文档/图片选择（只选文件、留文件名，不读取内容）

能力边界（务必如实告知用户）：
  * 本模块只调起系统文件选择器，把用户选中的文件名回传，作为"我上传的材料"记录。
  * 不读取图片/文档内容，不做 OCR、不解析 docx/pdf —— 那是后续独立功能。
  * Android 用 plyer.filechooser（底层 ACTION_GET_CONTENT，异步回调）；
    plyer 缺失或任何异常时降级：返回 None，由界面提示"当前不可用"，绝不假装成功。

平台说明：
  * Android：on_selection 回调里拿到的是 URI 或路径列表，取 basename 展示。
  * PC：plyer 走系统原生对话框，同样异步回调。
  * 本机无 plyer（仅内核自测环境）：select() 返回 None 并标记 unavailable。
"""

from __future__ import annotations

import os
from typing import Callable, Optional


class AttachUnavailable(Exception):
    """plyer 不可用或在当前平台不支持文件选择。"""


def _basename(path: str) -> str:
    """从路径或 URI 里取文件名，去掉 query 参数。"""
    name = str(path).split("?")[0].rstrip("/")
    return name.rsplit("/", 1)[-1] or name


def select_file(on_selected: Callable[[str], None],
                file_type: str = "image") -> bool:
    """
    调起系统选择器。user 选中后，回调 on_selected(文件名)。
    返回 True 表示已成功发起（结果稍后异步回调）；
    返回 False 表示不可用（已降级，无回调）。
    注意：Android 上本函数会立刻返回，真正的名字在 on_selected 里给。
    """
    try:
        from plyer import filechooser  # type: ignore
    except Exception:
        return False

    # filters 用 plyer 的语义键；无效键会退回 */*
    filters = {"image": "image", "doc": "pdf", "any": None}
    kwargs = {"on_selection": lambda sel: _handle(sel, on_selected)}
    ft = filters.get(file_type)
    if ft:
        kwargs["filters"] = [ft]

    try:
        filechooser.open_file(**kwargs)
        return True
    except Exception:
        return False


def _handle(selection, on_selected: Callable[[str], None]) -> None:
    """plyer 回调入口：selection 是列表；取第一个文件名回传。"""
    if not selection:
        return
    first = selection[0] if isinstance(selection, (list, tuple)) else selection
    try:
        on_selected(_basename(first))
    except Exception:
        pass


if __name__ == "__main__":
    got = []
    _handle(["/sdcard/DCIM/证据照片.jpg?x=1"], lambda n: got.append(n))
    assert got == ["证据照片.jpg"], got
    assert _basename("content://com.android/provider/合同.pdf") == "合同.pdf"
    print("ATTACH_OK")
