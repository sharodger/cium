# GitHub Actions 云端构建 APK（无需本机 Linux）

## 原理

GitHub 免费提供 Linux 云主机。把项目代码推到 GitHub 仓库，仓库里的
`.github/workflows/build-android.yml` 会自动在那台 Linux 机器上装 Buildozer、
构建 APK，并把 APK 作为下载文件（Artifact）放到网页上。你从网页下载 APK 拷到手机即可。

**全程不用在本机装 Docker / Java / WSL2 / Buildozer。**

## 第一次使用（约 10 分钟，只需做一次）

### 第 1 步：Git 已装好，注册 GitHub

- **Git 已经装好了**（Git 2.56.1，装在 `C:\Program Files\Git\`），无需再装。
  之前截图里 `git 不是内部或外部命令` 是因为装之前开的 cmd 窗口——
  **请关掉旧 cmd，重新打开一个新窗口**，git 命令就可用了。
- 已全局配置 `http.schannelCheckRevoke=false`，解决本机 Windows 的证书吊销检查失败问题
  （否则 `git push` 会报 `CRYPT_E_REVOCATION_OFFLINE`）。已验证能连 GitHub。
- GitHub 账号：若还没有，到 https://github.com 注册（免费）。
  从截图看你已用 `sharodger` 这个账号，若已注册可跳过。

### 第 2 步：在 GitHub 网页上建一个空仓库

1. 点右上角 `+` → `New repository`。
2. Repository name 填 `ownerrightsai`（任意英文即可）。
3. 选 **Public**（公开仓库，Actions 完全免费；私有仓库免费额度有限）。
4. **不要**勾选 "Add a README file"（建空仓库）。
5. 点 `Create repository`，记下页面显示的地址，形如：
   `https://github.com/你的用户名/ownerrightsai.git`

> **重要**：必须先在第 2 步网页上建好仓库，第 3 步的 `git push` 才能成功。
> 若仓库不存在，push 会失败。从截图看你的账号是 `sharodger`，
> 那你建的仓库地址就是 `https://github.com/sharodger/ownerrightsai.git`。

### 第 3 步：在本机把项目推上去

在项目目录 `D:\Agent Project\业主维权AI助手` 打开命令行（地址栏输 `cmd` 回车），依次执行：

```bash
git init
git add .
git commit -m "业主维权AI助手 Android 构建"
git branch -M main
git remote add origin https://github.com/你的用户名/ownerrightsai.git
git push -u origin main
```

> 推送时会弹 GitHub 登录窗口，用浏览器完成登录即可（Git 新版支持）。

## 触发构建（三选一）

代码推上去后，任选一种方式触发：

1. **手动（推荐先试这个）**：打开仓库网页 → `Actions` 标签 → 左侧点 `Build Android APK` → 右侧 `Run workflow` → 再点绿色 `Run workflow`。
2. **推送代码**：以后每次 `git push` 到 main 都会自动构建。
3. **打标签**：`git tag v1.0 && git push origin v1.0`，适合发版本。

## 下载 APK

1. 构建开始后，在 `Actions` 页能看到运行中的任务（首次约 20-40 分钟，因为要下载 SDK/NDK 数 GB）。
2. 构建成功后点进这次运行，页面下方 `Artifacts` 区有 `ownerrightsai-debug-apk`。
3. 点击下载得到 zip，解压出 `.apk` 文件。
4. 把 APK 传到手机 → 允许"安装未知来源应用" → 点击安装。

> 以后再构建，云主机会用缓存的 SDK/NDK，快很多（几分钟）。

## 常见问题

| 问题 | 处理 |
|---|---|
| Actions 页看不到工作流 | 确认 `.github/workflows/build-android.yml` 已随 `git push` 推上去；文件在隐藏目录，`git add .` 会包含它 |
| 构建失败（红色 X） | 点进运行页看日志，最常见是 requirements 里某个包版本问题，把日志发我 |
| 找不到 APK 下载 | 只有构建成功才有 Artifact；失败则无 |
| 免费额度 | 公开仓库 Actions 免费；私有仓库每月 2000 分钟，构建一次约 20-40 分钟 |
| 装到手机解析包错误 | 确认手机 Android ≥ 5.0（minapi 21）；64 位机型可把 spec 的 `android.arch` 改成 `arm64-v8a` 重新构建 |

## 安全说明

- APK 是 debug 包，可直接在手机安装测试，无需签名证书。
- 正式上架应用商店需要 release 签名，属于后续步骤，当前不含。
- 仓库建议保持 Public 以免费使用 Actions；项目本身不含隐私数据。
