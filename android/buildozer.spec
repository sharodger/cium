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
source.include_exts = py,png,jpg,kv,atlas,json,zip,txt,md,ttf,traineddata
source.exclude_dirs = build, bin, .buildozer, android, __pycache__, .git, selftest.py

# 明确包含核心目录（p4a 会把这些目录的 py 打进 apk）
source.include_patterns = core/*.py,legal/*.py,legal/ui/*.py,legal/dist/*.json,legal/dist/*.zip,assets/fonts/*.ttf,assets/tessdata/*.traineddata

# 版本号
version = 1.0.0
version.code = 1

# 依赖：python3 + kivy 固定版本；requests 下载更新包；plyer 调系统文件选择器（上传/识图选图）
# pyjnius 调 Tesseract4Android 的 Java API（kivy 自带，显式列出便于排查）
# 其余是 requests 移动端传递依赖
requirements = python3,kivy==2.3.2,requests,certifi,charset-normalizer,plyer,pyjnius

# Android 原生依赖：Tesseract4Android 单线程版（JitPack 坐标）
# p4a 的 gradle 模板只配了 google()/mavenCentral()，而本库只发布在 JitPack。
# 必须显式加 JitPack 仓库，否则依赖解析不到，报 :checkDebugAarMetadata 失败。
#
# 关键坑1：buildozer 的 getlist() 只按逗号切分+strip，不处理引号。
# 若写成 "maven { url '...' }"，外层双引号会被当作字面量传进 build.gradle，
# Gradle 不识别 → 等于没加。所以：外层不加引号，内层用双引号，且整行不能有逗号。
#
# 关键坑2：坐标必须带 @aar。该库 POM 只有一条传递依赖
# androidx.annotation:annotation:1.3.0；不带 @aar 时 Gradle 会解析它，
# 随后 :checkDebugAarMetadata 强制要求 android.useAndroidX=true。
# 而启用 AndroidX 会让 SDLActivity.nativeSetenv 在手机上启动闪退。
# @aar 是 Gradle 的 artifact-only 写法：只读 AAR 本身，跳过 POM 和传递依赖。
android.gradle_dependencies = cz.adaptech.tesseract4android:tesseract4android:4.9.0@aar
android.add_gradle_repositories = maven { url "https://jitpack.io" }

# 只保留 armeabi-v7a 的 native 库。
# Tesseract4Android AAR 自带 arm64-v8a/x86/x86_64 的 so，但 p4a 这里只构建 armeabi-v7a。
# 64 位手机看到 APK 里有 arm64-v8a 目录就只从该目录加载 so，而里面没有 libSDL2.so，
# 于是 PythonActivity 调 SDLActivity.nativeSetenv 时报 UnsatisfiedLinkError 闪退。
# 把这些多余 ABI 的 so 排除掉，手机才会回退到完整的 armeabi-v7a 目录。
android.add_packaging_options = jniLibs.excludes += 'lib/arm64-v8a/*.so', jniLibs.excludes += 'lib/x86/*.so', jniLibs.excludes += 'lib/x86_64/*.so'

# 屏幕方向：工具型应用，竖屏为主
orientation = portrait

# 权限：INTERNET 用于检查法规库更新；存储权限用于读写法规库/文书（Android 10 以下）
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

# API 级别：p4a 推荐最低 21，目标 35
android.api = 35
android.minapi = 21
android.sdk = 35
android.ndk = 25c
# 不要启用 AndroidX。
# 血泪教训：旧版用无效键 use_androidx（实际未启用）时能正常打开；
# 一旦改成 enable_androidx=True，启动即在 SDLActivity.nativeSetenv 报
# UnsatisfiedLinkError（native 库符号不匹配）。
# Tesseract4Android 4.9.0 的 AAR 只引用 androidx.annotation.*（编译期注解，
# compileSdk 自带），无 Kotlin/运行时 AndroidX 依赖，因此无需启用 AndroidX。
android.enable_androidx = False

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
