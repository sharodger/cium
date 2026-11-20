# Android APP 打包说明（业主维权AI助手）

> **不想在本机装 Linux？** 用 GitHub Actions 云端构建，推代码自动出 APK：
> 见 `android/GITHUB_ACTIONS构建说明.md`（推荐）。本文件讲的是本机 Linux/WSL2 构建法。

## 状态（如实标注）

- 本目录的打包配置**已写好，但未在本机构建验证**。
- 原因：Buildozer 底层是 python-for-android，**只能在 Linux / WSL2 运行，Windows 原生不行**；当前开发机是 Windows 且没有 WSL2 / Docker / Java，无法在此真正产出 APK。
- 配置本身按 p4a 规范编写，拿到 Linux / WSL2 环境即可构建。

## 一、准备 Linux / WSL2 环境

Windows 上二选一：

- **WSL2**：管理员 PowerShell 执行 `wsl --install -d Ubuntu-22.04`，重启后进入 Ubuntu。
- **虚拟机**：VMware / VirtualBox 装 Ubuntu 22.04。

> 若你的 Windows 无法装 WSL2，可用任意一台 Linux 机器（含云主机）构建，产物 APK 与构建机器无关。

## 二、一键构建

把整个 `业主维权AI助手` 文件夹拷到 Linux / WSL2 里，然后：

```bash
cd 业主维权AI助手
bash android/build_android.sh
```

脚本会自动：检查源码 → 装系统依赖 → 装 buildozer → 复制 spec → 构建 debug APK。

首次构建会下载 Android SDK / NDK（约数 GB，耗时较长），失败时先清理再重试：

```bash
python3 -m buildozer android clean
bash android/build_android.sh
```

产物在 `bin/` 目录：`业主维权AI助手-1.0.0-armeabi-v7a-debug.apk`。

## 三、复制到手机安装测试

1. 把 `bin/*.apk` 传到手机（数据线 / 微信 / 网盘均可）。
2. 手机设置 → 安全 → 打开「安装未知来源应用」（允许通过文件管理器安装）。
3. 用文件管理器找到 APK，点击安装。
4. 首次打开会检测设备、初始化本地存储，界面顶部显示法规库版本与设备标识。

> 需要 64 位机型时可改 `buildozer.spec` 的 `android.arch = arm64-v8a` 重新构建。

## 四、当前 APP 能力与降级说明（不虚构）

本 APK 打包的是**主系统骨架**：Kivy 界面、内核路由、法规库本地检索、法规库更新面板、设置与隐私清除。语音对话 / 旁听模式目前是占位按钮。

| 能力 | Android 现状 | 处理方式 |
|---|---|---|
| 法规库更新 | 支持 | 需联网下载更新包；无网络时用本地演示包 |
| 语音识别 | 未集成 | 统一走 Vosk；需 p4a recipe + 模型文件，属后续功能，当前不声称可用 |
| 图片 OCR | 未集成 | Tesseract 无稳定 p4a recipe，当前不声称可用 |
| 文书生成 docx | 未集成 | Android 用 zipfile+XML 或纯文本模板，属后续功能 |
| 本地大模型 | 不支持 | Ollama 无 Android 版；换端侧框架或规则检索，不声称能跑 Ollama |
| 原生能力桥接 | 预留 | Pyjnius 仅用于权限/设备信息/文件访问，不用于语音 |

## 五、已知技术风险（构建时若遇到问题按此排查）

1. **`__file__` 路径**：app.py 用 `Path(__file__).resolve().parent` 定位 legal/。Android 入口 `main.py` 已做路径兜底；若仍报模块找不到，确认 spec 的 `source.include_patterns` 包含了 `legal/*.py` 与 `core/*.py`。
2. **requests 的 file://**：法规库演示更新源是 `file://`，requests 不支持，downloader.py 已做分流（file 走 urllib），Android 上同样生效。
3. **Cython 版本**：p4a 需要 `cython<3`，脚本已固定；若报 Cython 相关错误，执行 `pip install "cython<3"` 后 `buildozer android clean` 重试。
4. **SDK/NDK 下载失败**：检查网络；必要时手动下载到 `~/.buildozer/android/platform/` 后重试。
