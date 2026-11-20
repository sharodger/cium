#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# 一键构建 Android debug APK（业主维权AI助手）
#
# 运行环境：Linux 或 WSL2（Ubuntu 22.04+）。Windows 原生不行。
# 用法：
#   cd 项目根目录（含 main.py / app.py / core / legal）
#   bash android/build_android.sh
# 产物：
#   bin/业主维权AI助手-1.0.0-*-debug.apk
#
# 说明：脚本只做构建准备 + 调用 buildozer，不改任何源码。

set -e  # 任一步失败即停止

# 定位项目根目录（本脚本在 android/ 下，上级即根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT"

echo "== 项目根目录: $ROOT =="

# 1) 环境检查：必须是 Linux
if [ "$(uname -s)" != "Linux" ]; then
  echo "[错误] 本脚本只能在 Linux / WSL2 运行，当前: $(uname -s)"
  echo "        Windows 请先在设置里启用 WSL2 并安装 Ubuntu。"
  exit 1
fi

# 2) 检查构建必需的入口文件是否齐全
for f in main.py app.py core/router.py core/templates.py legal/database.py legal/device.py; do
  if [ ! -f "$f" ]; then
    echo "[错误] 缺少文件: $f"
    exit 1
  fi
done
echo "== 源码文件检查通过 =="

# 3) 安装系统依赖（已装会跳过，重复运行安全）
echo "== 安装系统依赖（可能需要 sudo 密码）=="
sudo apt update -y
sudo apt install -y git zip unzip openjdk-17-jdk autoconf libtool \
  pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 \
  cmake libffi-dev libssl-dev python3-pip

# 4) 安装 buildozer 与 Cython（p4a 需要固定旧版 Cython）
echo "== 安装 buildozer =="
python3 -m pip install --user --upgrade buildozer "cython<3"

# 5) 复制 spec 到项目根目录（buildozer 默认读根目录的 buildozer.spec）
cp -f android/buildozer.spec ./buildozer.spec
echo "== 已复制 android/buildozer.spec -> ./buildozer.spec =="

# 6) 构建 debug APK
#    首次构建会下载 Android SDK/NDK（数 GB），较慢；失败可先 buildozer android clean
echo "== 开始构建 APK（首次较慢，请耐心）=="
python3 -m buildozer -v android debug

echo ""
echo "== 构建结束。APK 在 bin/ 目录下：=="
ls -lh bin/*.apk 2>/dev/null || echo "未找到 APK，请查看上方构建日志。"
