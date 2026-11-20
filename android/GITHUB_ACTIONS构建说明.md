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
  （否则 `git push` 会报 `CRYPT_E_REVOCATION_OFFLINE`）。
  **但这只解决证书检查，不代表网络已连通 GitHub**；当前网络实测仍可能超时，
  遇到 `Failed to connect to github.com port 443` 请按文末"推送失败排查"处理。
- GitHub 账号：若还没有，到 https://github.com 注册（免费）。
  从截图看你已用 `sharodger` 这个账号，若已注册可跳过。

### 第 2 步：确认 GitHub 仓库

仓库已创建并确认是公开空仓库：

```text
https://github.com/sharodger/cium.git
```

默认分支是 `main`。本步骤已完成，无需再做任何操作。

> 本地远程地址已同步指向该仓库。若以后换电脑克隆，使用上面的地址即可。

### 第 3 步：推送（本地已备好，只需一条命令）

**本机已由助手完成**：Git 安装、证书配置、仓库初始化、代码提交、remote 设置。
你**不用**再执行 `git init / add / commit / remote add`——这些都已做好。

**关掉旧 cmd，重新打开一个新 cmd 窗口**（这样 PATH 才有 git），执行：

```bash
cd /d "D:\Agent Project\业主维权AI助手"
git push -u origin main
```

> 推送时会弹 GitHub 登录窗口，用浏览器完成登录即可（Git 新版支持）。
> 若提示输入用户名/密码，用户名填 `sharodger`，密码用 **Personal Access Token**
> （GitHub → Settings → Developer settings → Personal access tokens 生成，勾选 repo 权限）。
> 这一步涉及你的 GitHub 账号登录，**必须由你本人操作**，助手无法代登录。

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

## 推送失败排查（截图中的报错）

截图里的错误是：

```text
fatal: unable to access 'https://github.com/sharodger/cium.git/':
Failed to connect to github.com port 443 after 21029 ms: Could not connect to server
```

这不是代码错误，也不是本地仓库出错，而是**本机到 GitHub 的 443 端口没有连通**。
截图前面两条 `cd` 报错可忽略：一条把路径中的"业主"输成了别的字，另一条是多余的 `cd d`；
当前目录本来就已经在 `D:\Agent Project\业主维权AI助手`。

先确认仓库已按第 2 步创建，再按下面任选一种方式。

### 方案 A：给 Git 设置你自己的代理

如果你电脑上有代理软件，先确认它的本地端口（常见为 `7890`，以软件界面显示为准），
然后在**新打开的 cmd** 中执行（把 `7890` 换成实际端口）：

```bat
set HTTP_PROXY=http://127.0.0.1:7890
set HTTPS_PROXY=http://127.0.0.1:7890
git config --global http.proxy http://127.0.0.1:7890
git config --global https.proxy http://127.0.0.1:7890
git ls-remote origin
```

`ls-remote` 能列出内容后，再执行：

```bat
cd /d "D:\Agent Project\业主维权AI助手"
git push -u origin main
```

若没有代理软件，不要随便填端口，直接用方案 B。

### 方案 B：改用 SSH 的 443 端口（推荐，绕开 HTTPS 443 限制）

本方案**本地已配置完成**，无需再生成密钥或写 config：

- 专用密钥：`C:\Users\Administrator\.ssh\id_ed25519_cium`
- 配置文件：`C:\Users\Administrator\.ssh\config`（别名 `github-cium`，走 `ssh.github.com:443`）
- 本地 origin 已设为：`git@github-cium:sharodger/cium.git`
- 已实测 SSH 443 端口可达，当前只差把公钥授权到 GitHub

你现在只需把下面这一整行公钥复制到 GitHub → `Settings` → `SSH and GPG keys` → `New SSH key`：

```text
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP7AHwvsq2kU2rFo1J5CkESCUX09u28UdT4ppa4V9s1M github-cium
```

然后测试并推送：

```bat
ssh -T github-cium
cd /d "D:\Agent Project\业主维权AI助手"
git push -u origin main
```

`ssh -T` 出现 `Hi sharodger! You've successfully authenticated` 即成功。
如果出现 `Permission denied (publickey)`，说明公钥尚未添加到 GitHub
或复制时漏了字符。推送成功后按前面"触发构建"手动运行 Actions。

### 注意

- 如果之前设置过代理又想改走 SSH，先清掉代理配置：

```bat
git config --global --unset http.proxy
git config --global --unset https.proxy
```

- **不要把 GitHub 用户名/密码或 Token 发给任何第三方"加速镜像"网站。**
- 推送这一步涉及你的 GitHub 账号登录或 SSH 密钥，必须由你本人完成；
  助手只能把本地仓库、远程地址和命令准备好。

## 安全说明

- APK 是 debug 包，可直接在手机安装测试，无需签名证书。
- 正式上架应用商店需要 release 签名，属于后续步骤，当前不含。
- 仓库建议保持 Public 以免费使用 Actions；项目本身不含隐私数据。
