# 把 dsh-video-kit 上架到 DSH 插件市场

市场没有"上传"接口。收录 = 在 `awesome-dsh-plugin/awesome-dsh-plugin` 提一个**只加一个 YAML 文件**的 PR。
下面按顺序做，每步都能验证结果。

---

## 第 0 步 先看清单（这个包已经准备好的东西）

- `package.json` 版本 1.2.1，已声明 `dsh.bundle.patch`，已补 `repository`/`homepage`/`bugs`
- `cordis.patch.yml` 在仓库根
- `dsh-video-kit.tgz` 已打好（28.8 KB，15 个文件，**资产名不带版本号**）
- `market-submission/shisuiqingqian__dsh-video-kit.yml` 就是要提的 PR 文件
- 本目录已 `git init` 并提交过一次

---

## 第 1 步 在 GitHub 建仓库

1. 打开 https://github.com/new
2. Repository name 填 **`dsh-video-kit`**（必须和小写一致）
3. 选 **Public**（市场要能读到你仓库，私有仓库不会收录）
4. **不要**勾 "Add a README"、"Add .gitignore"、"Choose a license"（本地已有）
5. Create repository

---

## 第 2 步 推代码上去

在本目录（`C:\Users\23038\Desktop\dsh-video-kit`）开 PowerShell：

```powershell
git remote add origin https://github.com/shisuiqingqian/dsh-video-kit.git
git branch -M main
git push -u origin main
```

第一次推会弹出浏览器让你登录 GitHub 授权，登录 `shisuiqingqian` 这个账号即可。

验证：仓库页能看到 15 个文件，且首页渲染出 README。

---

## 第 3 步 加 topic

仓库页右上角 **⚙️**（About 右边）→ Topics 输入 `dsh-plugin` → 回车 → Save changes。

---

## 第 4 步 发 Release 并上传 tgz

1. 仓库页右侧 **Releases** → **Create a new release**
2. Choose a tag 填 **`v1.2.1`** → 点 "Create new tag: v1.2.1 on publish"
3. Release title 填 `1.2.1`
4. 把本目录的 **`dsh-video-kit.tgz`** 拖进 "Attach binaries"
5. Publish release

⚠️ 资产名必须是 `dsh-video-kit.tgz`（不带版本号）。因为 YAML 里写的是
`releases/latest/download/dsh-video-kit.tgz`，`latest` 会解析到最新版，但文件名是照字面取的——
资产名一旦带上版本号，下次发版这个链接就静默 404。

验证：浏览器打开
https://github.com/shisuiqingqian/dsh-video-kit/releases/latest/download/dsh-video-kit.tgz
应当直接下载。

---

## 第 5 步 提 PR（只有这一件事是真投稿）

1. 打开 https://github.com/awesome-dsh-plugin/awesome-dsh-plugin
2. 点 **Fork**（在你账号下建一份副本）
3. 在你 fork 的仓库里：**Add file → Create new file**
4. 文件名填（注意是双下划线）：

```
data/plugins/shisuiqingqian__dsh-video-kit.yml
```

5. 内容贴本目录 `market-submission/shisuiqingqian__dsh-video-kit.yml` 全部内容
6. Commit message 填 `Add shisuiqingqian/dsh-video-kit` → **Propose new file**
7. 回到原仓库点 **Compare & pull request**，标题 `Add shisuiqingqian/dsh-video-kit`
8. 正文（可选但建议）贴：

```
Adds dsh-video-kit: three tools (video_read / video_discover / video_kit_setup) that turn a local video or page link into a timestamped transcript plus key-frame images, using ffmpeg, sherpa-onnx Paraformer and yt-dlp. Runtime deps and the ~234 MB ASR model are fetched on first use; the package ships no binaries.
```

9. **Create pull request**

---

## 第 6 步 CI 与合并

CI 依次检查：

1. 一个 PR 最多 3 条目 —— 本次 1 条
2. 读你仓库 `package.json` 的 `dsh.bundle` —— 有
3. 仓库创建满 1 天 —— **今天刚建的话，明天再提，或被 CI 挡下后隔天重提即可**
4. awesome-lint 与站点构建 —— 描述格式已对齐

失败会在 PR 里指名道姓告诉你改哪一行，**推同一个分支即可，不用重开 PR**。
合并后站点自动重建，`dshmarket` 面板里就能搜到，可一键装、可开关。

---

## 装到别人机器上是什么命令

```bash
dsh plugin --profile web add "https://github.com/shisuiqingqian/dsh-video-kit/releases/latest/download/dsh-video-kit.tgz"
```

或从源码构建：

```bash
dsh plugin --profile web add github:shisuiqingqian/dsh-video-kit
```

装完重启 DSH，新会话里出现 `video_read` / `video_discover` / `video_kit_setup`。
首次调用会自己下运行时（约 290 MB），之后全离线；数据落在 `~/.dsh/toolkits/video-kit/`。

---

## 可选加分项

- **截图**：仓库根放 `screenshots.json`，列出 1–8 张仓库内相对路径图片，市场详情页会像 App Store 那样展示。不写则会从 README 自动抽图。
- **发 npm**：市场会展示下载量并按它排序；不影响收录，可后补。
