# -*- coding: utf-8 -*-
#
# Buildozer 打包配置 —— 业主维权AI助手（Android）
#
# 【环境要求 · 重要】
#   Buildozer 底层 python-for-android 不能在 Windows 原生运行。
#   必须在 Linux / WSL2（Ubuntu 22.04+）里执行。当前是 Windows 环境，
#   本 spec 已按 p4a 规范写好，但未在本机构建验证，需到 Linux/WSL2 上构建。
#
# 【一键构建（Linux / WSL2 中）】
#   cd 到本目录的上一级（项目根目录，含 main.py / app.py / core / legal）
#   cp android/buildozer.spec ./buildozer.spec
#   bash android/build_android.sh        # 脚本会装依赖并构建 debug APK
#   产物：bin/业主维权AI助手-1.0.0-armeabi-v7a-debug.apk
#
# 【复制到手机测试】
#   把 bin/*.apk 传到手机 → 设置里允许「安装未知来源应用」→ 点击安装。
#   debug 包可直接安装，无需签名证书。

[app]

# 应用基本信息
title = 业主维权AI助手
package.name = ownerrightsai
package.domain = org.wbw

# 入口：Android 专用 main.py（相对 spec 所在的项目根目录）
source.dir = .
source.entrypoint = main.py

# 需要打进 apk 的源码类型与目录：主系统 + core + legal 子系统 + 更新包
source.include_exts = py,png,jpg,kv,atlas,json,zip,txt,md,ttf
source.exclude_dirs = build, bin, .buildozer, android, __pycache__, .git, selftest.py

# 明确包含核心目录（p4a 会把这些目录的 py 打进 apk）
source.include_patterns = core/*.py,legal/*.py,legal/ui/*.py,legal/dist/*.json,legal/dist/*.zip,assets/fonts/*.ttf

# 版本号
version = 1.0.0
version.code = 1

# 依赖：python3 + kivy 固定版本；requests 下载更新包；plyer 调系统文件选择器（上传）
# 其余是 requests 移动端传递依赖
requirements = python3,kivy==2.3.2,requests,certifi,charset-normalizer,plyer

# 屏幕方向：工具型应用，竖屏为主
orientation = portrait

# 权限：INTERNET 用于检查法规库更新；存储权限用于读写法规库/文书（Android 10 以下）
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

# API 级别：p4a 推荐最低 21，目标 35
android.api = 35
android.minapi = 21
android.sdk = 35
android.ndk = 25c
android.use_androidx = True

# 云端构建必须自动接受 Android SDK 许可，否则 build-tools 会被跳过，
# 接着报 "build-tools folder not found" / "Aidl not found"。
android.accept_sdk_license = True

# 架构：先打 armeabi-v7a，兼容绝大多数安卓机；64 位机型可在构建脚本里加 arm64-v8a
android.arch = armeabi-v7a

# Python 构建目录
build_dir = .buildozer
bin_dir = bin

[buildozer]

log_level = 2
warn_on_root = 1
