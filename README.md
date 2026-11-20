# 业主维权AI助手

PC 端与移动端共用的本地优先工具。把业主的口语化描述拆成**依据、步骤、文书**，
核心逻辑本地执行，联网仅辅助获取法规更新，不依赖外部大模型接口。

> 本工具提供信息整理与行动建议，不构成正式法律意见。重大事项请咨询执业律师或拨打 12348。

---

## 当前阶段：主系统骨架（已完成）

本次只完成**主系统搭建**，其它功能按增量方式后续逐个加入。

### 已实现
- **Kivy 主界面**：顶部状态栏（法规库版本、设备标识、下载后端）、中部对话时间线、底部输入区、设置入口。
- **内核骨架**：
  - `core/router.py`：按触发词给六大模块 A-F 打分，输出 `[路由: A→E→D]` 标签；无匹配走综合类。
  - `core/templates.py`：系统提示词第七节的八段式输出模板，自动附免责声明。
  - `app.py::answer()`：路由 → 本地法规检索 → 八段式组装，纯规则，不调用大模型。
- **法规库子系统**（`legal/`）：复用已跑通的模块，支持版本更新、SQLite 存储、全文检索、设备标识。
- **设置弹窗**：挂载法规库更新面板（检查/下载/应用/回滚）、隐私清除、关于。

### 后续功能入口（本次只占位，未实现）
| 功能 | 入口位置 | 当前行为 |
|---|---|---|
| 语音对话 | 底部「语音」按钮 `RootWidget.on_voice()` | 提示"后续功能"，后续接本地 Vosk 离线转写 |
| 旁听模式 | 底部「旁听」按钮 `RootWidget.on_monitor()` | 提示"后续功能" |
| 图片识别 | 后续在输入区加按钮 | 后续接本地 Tesseract OCR |
| 文书生成 | 后续在输出模块加 | PC 用 python-docx，移动端降级 zipfile+XML/纯文本 |
| 本地大模型推理 | 后续替换 `answer()` 的推理部分 | PC 可接 Ollama，移动端规则检索 |

---

## 目录结构

```
业主维权AI助手/
├── 业主维权AI助手.bat      Windows 双击启动器（推荐）
├── 业主维权AI助手.py       跨平台命令行入口
├── main.py                Android 打包入口（Buildozer 默认入口）
├── app.py                 主系统实现（Kivy App + 内核编排，入口调用它）
├── selftest.py            主系统自测（14 项）
├── core/
│   ├── router.py          路由引擎（六大模块打分 -> 路由标签）
│   └── templates.py       八段式输出模板
├── legal/                 法规库子系统（原样复用，内部代码未改）
│   ├── device.py          设备标识与跨设备检测
│   ├── database.py        SQLite 法规库
│   ├── package.py         更新包格式与校验
│   ├── downloader.py      下载（requests/urllib 降级）
│   ├── updater.py         更新引擎
│   ├── ui/update_panel.py 法规库更新面板
│   ├── tools/             更新包生成工具
│   └── dist/              演示更新包
├── android/               Android 打包配置（需 Linux/WSL2，详见 android/README.md）
│   ├── buildozer.spec     Buildozer 配置
│   ├── build_android.sh   一键构建脚本
│   └── README.md          构建与安装说明
└── ui/                    （预留，后续放主界面拆分组件）
```

---

## 运行与自测

```bash
# 依赖（Python 3.13 实测可用）
pip install kivy requests pyinstaller

# 自测（不需要窗口，自动用 mock GL 后端）
python selftest.py          # 14/14 通过

# 运行应用（需有图形环境）
# 方式一：Windows 直接双击「业主维权AI助手.bat」（推荐）
#   会自动探测带 kivy 的 Python，顺序：PATH 里的 python -> py -3 -> WorkBuddy 内置 Python。
#   每个候选都用 "import kivy" 验证，跳过损坏/缺依赖的解释器；窗口会打印最终选中的 Python。
# 方式二：命令行入口（跨平台，需 python 在 PATH 中）
python 业主维权AI助手.py
# 方式三：直接跑实现文件（等价）
python app.py
```

> **双击报 "python is not recognized" 怎么办**：`业主维权AI助手.bat` 已内置探测，无需手动配 PATH。
> 若三个候选都没有装 kivy，会提示 `No Python with kivy found`，此时在命令行装依赖即可：
> `pip install kivy requests`。若系统 `py` 启动器指向损坏的 Python，脚本会自动跳过它。

## Android 打包

本 Windows 环境**无法**直接构建 APK（Buildozer 只能在 Linux/WSL2 运行）。两条路：

**方式一：GitHub Actions 云端构建（推荐，无需本机 Linux）**
把代码推到 GitHub 仓库，`.github/workflows/build-android.yml` 自动在云端 Linux 构建 APK，
完成后从 Actions 页面下载 Artifact。详细步骤见 `android/GITHUB_ACTIONS构建说明.md`。

**方式二：本机 Linux / WSL2 构建**
```bash
cd 业主维权AI助手
bash android/build_android.sh     # 自动装依赖并构建，产物 bin/*.apk
```

把 `bin/*.apk` 拷到手机、允许安装未知来源即可安装测试。构建需下载 SDK/NDK（数 GB）。
**当前未在本机验证构建**（本机 Windows 无 WSL2/Hyper-V），能力边界与排错见 `android/README.md`。

法规库更新源默认指向 `legal/dist/` 的本地演示包；正式使用可在 `app.py` 里改 `update_manager` 的 URL。

---

## 设计说明

- **不重写已跑通代码**：`legal/` 子系统从已验证的 `legal_repo/` 原样复制，内部逻辑未动；主系统只用 `sys.path` 接入。
- **简单优先**：路由是关键词打分，检索用 LIKE 兜底（中文 FTS5 默认分词器不按词切分），都是本地规则，可读可改。
- **界面线程安全**：路由/检索放后台线程，UI 更新一律 `Clock.schedule_once` 回主线程。
- **降级明确**：空法规库时输出"待核实"，不编造法条；语音/旁听未实现就明确提示，不假装能用。
