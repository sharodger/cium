# -*- coding: utf-8 -*-
"""
main.py —— 业主维权AI助手 Android 打包入口（Buildozer/python-for-android 默认入口）

为什么单独做一个入口，而不是直接用 app.py？
  Buildozer 默认从项目根目录的 main.py 启动。app.py 里的平级导入
  （from device import ...）依赖 sys.path 注入 LEGAL_DIR，这条在 PC 上有效；
  在 Android 上，__file__ 指向 apk 内的虚拟路径，不能当普通目录读。
  p4a 会把所有 .py 作为模块打进 apk，因此这里用更稳妥的方式接入：
    - 以包名方式导入 legal 子系统（legal 目录下有 __init__.py 时）
    - 或用 Android 应用私有目录（app.user_data_dir）作为路径兜底

本文件不改 app.py 内部任何逻辑，只负责"把路径准备好，然后启动 App"。
"""

import os
import sys
from pathlib import Path

IS_ANDROID = sys.platform == "android" or "android" in sys.platform


def _prepare_sys_path() -> None:
    """让 app.py 需要的 core / legal 模块在 Android 上可被导入。"""
    if IS_ANDROID:
        # p4a 环境下，所有 py 文件被打进 apk 的 Python 模块搜索路径，
        # core 与 legal 作为子包可直接导入；app.py 内部的平级导入由其自身
        # 的 sys.path.insert 处理（HERE 在 Android 上通常指向 apk 内合法路径）。
        # 这里补一条：把当前工作目录也加入，兼容部分 p4a 版本的解包布局。
        cwd = os.getcwd()
        if cwd not in sys.path:
            sys.path.insert(0, cwd)
    else:
        # PC 上直接跑本文件时，行为与「业主维权AI助手.py」一致。
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)


_prepare_sys_path()

from app import OwnerRightsApp  # noqa: E402  （必须先 prepare path 再导入）


if __name__ == "__main__":
    OwnerRightsApp().run()
