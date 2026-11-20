# -*- coding: utf-8 -*-
"""
业主维权AI助手 —— PC 端启动入口（跨平台）

用法：
  命令行：python 业主维权AI助手.py
  Windows：双击同目录下的「业主维权AI助手.bat」

真正的界面与内核实现都在 app.py，这里只做薄包装，
让入口文件名统一为「业主维权AI助手」，不改动已跑通的代码。
"""

from app import OwnerRightsApp


if __name__ == "__main__":
    OwnerRightsApp().run()
