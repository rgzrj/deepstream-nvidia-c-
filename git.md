# Git 上传文件到 GitHub 完整指南

## 📦 第一步：初始化本地 Git 仓库

在终端中（你已经在此文件夹下），运行：

```bash
git init
```

这会在当前文件夹创建一个 `.git` 隐藏文件夹，把它变成一个本地 git 仓库。

---

## 👤 第二步：配置 Git 用户身份（必须！）

在提交之前，必须设置用户名和邮箱，否则 `git commit` 会报错：

```
Author identity unknown
fatal: unable to auto-detect email address
```

```bash
git config user.email "your-email@example.com"
git config user.name "Your Name"
```

> 加上 `--global`（如 `git config --global user.email "..."`）可全局生效，不加则仅对当前仓库生效。

---

## 📝 第三步：创建 .gitignore 文件（可选但推荐）

有些文件不该上传（比如编译产物、临时文件），先创建 `.gitignore`：

```bash
echo build/ > .gitignore
echo .claude/ >> .gitignore
echo .codex_tmp/ >> .gitignore
echo .codex_tmp_latest_odt.txt >> .gitignore
```

> ⚠️ **注意：不要加引号！** `echo "build/"` 会把双引号也写入文件，导致 git 无法识别。gitignore 每一行就是纯文本，不需要引号。

---

## 📂 第四步：添加所有文件到暂存区

```bash
git add .
```

这会把当前文件夹下所有文件（`.gitignore` 里排除的除外）加入"待提交"状态。

---

## ✅ 第五步：提交（创建第一个 commit）

```bash
git commit -m "first commit"
```

---

## 🌐 第六步：在 GitHub 上创建远程仓库

1. 打开浏览器，登录 [github.com](https://github.com)
2. 点击右上角的 **+** → **New repository**
3. 给仓库起个名字（比如 `deepstream-project`）
4. **不要**勾选 "Add a README file"（因为你本地已经有了）
5. 点击 **Create repository**

创建完后，GitHub 会显示一个远程地址，类似：
```
https://github.com/rgzrj/deepstream-nvidia-c-.git
```

---

## 🔗 第七步：关联远程仓库并推送

把远程地址替换成你自己的，然后运行：

```bash
git remote add origin https://github.com/rgzrj/deepstream-nvidia-c-.git
git branch -M main
git push -u origin main
```

> ⚠️ 如果 `git push` 报错 `src refspec main does not match any`，说明还没有任何 commit —— 请先完成第五步的 `git commit`。

---

## 🔐 关于身份验证

如果你是第一次用 GitHub，推送时可能会要求你登录。有两种方式：

| 方式 | 说明 |
|------|------|
| **GitHub CLI（推荐）** | 运行 `gh auth login` 按提示操作 |
| **Personal Access Token** | 在 GitHub → Settings → Developer settings → Personal access tokens → 生成一个 token，推送时密码填这个 token |

---

## 🪟 Windows 下的 CRLF 警告

在 Windows 上 `git add` 时常见大量 `LF will be replaced by CRLF` 警告，这是正常的，不影响功能。如果想消除警告，可以配置：

```bash
git config core.autocrlf true
```

---

## 📋 总结命令清单

```bash
# 1. 初始化
git init

# 2. 配置用户身份（必须！）
git config user.email "you@example.com"
git config user.name "Your Name"

# 3. 创建 .gitignore（注意：不加引号！）
echo build/ > .gitignore
echo .claude/ >> .gitignore

# 4. 添加文件
git add .

# 5. 提交
git commit -m "first commit"

# 6. 关联远程仓库（替换成你的地址）
git remote add origin https://github.com/rgzrj/deepstream-nvidia-c-.git

# 7. 推送
git branch -M main
git push -u origin main
```
