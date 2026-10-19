# dsh-video-kit

给 **DeepSeek Harness** 装上"看视频"的能力：一次工具调用，把本地视频或网页链接变成**带时间轴的逐字稿** + **一组关键帧图片**，模型可以直接逐帧看。

bilibili / 腾讯视频 / YouTube 等站点链接交给 yt-dlp；字幕外的内容用 Paraformer 中文语音识别补齐；关键帧用 ffmpeg 抽，返回绝对路径，配合内置的 `read_image` 就能真看图。

---

## 三个工具

| 工具 | 作用 |
|---|---|
| `video_read` | 读一个视频：返回 `transcript`（时间轴逐字稿）、`frames`（关键帧绝对路径）、`outdir`、`duration` |
| `video_discover` | 先找后读：在抖音 / 小红书 / 公众号 / B站按关键词找候选视频，返回标题与 URL，再交给 `video_read` |
| `video_kit_setup` | 体检 / 安装运行时依赖与 ASR 模型（`check=true` 只体检） |

典型用法（对模型说）：

```
用 video_read 读 D:\videos\demo.mp4，每 10 秒抽一帧
```

模型拿到返回后会自己调 `read_image` 逐帧查看，再结合逐字稿回答。

---

## 检索需要登录的平台（video_discover）

抖音、小红书、公众号都不给未登录的搜索结果，而且**新版权 Chromium 不允许对默认浏览器 profile 开远程调试端口**。所以这里的做法是：插件维护一个自己的浏览器 profile，你在弹出的窗口里登录一次，登录态（DPAPI 加密的 cookie）留在那个目录里长期复用。插件从不接触你的账号密码。

三步：

```
video_discover action=login  platform=douyin     # 弹出窗口，你扫码/输验证码登录
video_discover action=status                      # 确认 douyin: 已登录
video_discover action=search platform=douyin query="数字人 教学"
```

返回的 `items[].url` 直接喂给 `video_read` 即可转写抽帧。

- 登录态一般 7–30 天失效，失效了重复一次 `action=login`
- 未登录时不会崩，会返回 `loggedIn=false` 加 `warning`
- 只读列表页，不点赞、不评论、不发布；默认单次检索不做并发
- `platform=bilibili` 不需要登录，可用来验证 CDP 链路是否通
- 浏览器 profile 目录：`~/.dsh/toolkits/video-kit/browser`；端口默认 9333（`VIDEO_CDP_PORT` 可改）

---

## 安装

### 方式一：脚本（推荐）

```powershell
# 解压后进入 dsh-video-kit 目录
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

脚本会做五件事：铺文件到 `~/.dsh/local-plugins/`、同步进 `profiles/<profile>/node_modules/`、登记 `file:` 依赖、在 **profile 补丁层**写入挂载块、最后跑一次依赖体检。

可选参数：

| 参数 | 说明 |
|---|---|
| `-Profile <名字>` | 目标 profile，默认 `desktop` |
| `-NoPatch` | 只铺文件，不写挂载（你想手工挂） |
| `-WhatIfOnly` | 只打印计划，不改任何东西 |

### 方式二：手工（三步）

1. 把整个目录复制到 `%USERPROFILE%\.dsh\local-plugins\dsh-video-kit`
2. 再把同一份复制到 `%USERPROFILE%\.dsh\profiles\desktop\node_modules\dsh-video-kit`
3. 在 `%USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml` **末尾**追加：

```yaml
# 本地插件：视频读取工具（video_read），进程级挂载
- insert:
    - id: tool-video-kit
      name: "dsh-video-kit"
```

并在同目录 `package.json` 的 `dependencies` 里加一行 `"dsh-video-kit": "file:../../local-plugins/dsh-video-kit"`（防止包管理器清理 node_modules）。

### 方式三：作为依赖安装

```powershell
cd %USERPROFILE%\.dsh\profiles\desktop
pnpm add file:../../local-plugins/dsh-video-kit
```

装完仍需在 `cordis.patch.yml` 写挂载块（同上）。

---

## 装完必须做两件事

1. **完全退出并重新打开 DeepSeek Harness** —— 插件在进程启动时加载，热改不生效。
2. **新开一个会话** —— 已有会话的工具表在建立时就冻结了，不会热更新。这是最容易被误判成"插件没装上"的原因：同一个进程里，老会话看不到 `video_read`，新会话立刻就有。

---

## 参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `source` | string | 必填 | 本地视频绝对路径，或 http(s) 视频链接 |
| `every` | number | 20 | 每隔多少秒抽一帧；短视频会自动加密到 2 秒 |
| `maxframes` | number | 24 | 最多抽多少帧 |
| `copyTo` | string | — | 把关键帧与逐字稿复制到这个目录，**返回复制后的路径** |
| `timeoutMs` | number | 900000 | 整体超时；10 分钟视频约需 1–3 分钟处理 |

### `copyTo` 什么时候必须用

DSH 给模型看图时，会把图片复制一份到 `~/.dsh/attachments/`。**如果当前会话的文件策略是 `workspace-write`，这个目录在工作区之外，写不进去**，于是页面会显示"图片无法预览"——文件其实是好的。

传一个**工作区内的绝对路径**即可绕开：

```
用 video_read 读 D:\videos\demo.mp4，copyTo 传 C:\Users\你\工作区\.frames
```

---

## 数据目录

模型和产物不随包分发（模型 227 MB），统一放在：

```
%USERPROFILE%\.dsh\toolkits\video-kit\
  models\asr-paraformer-zh\model.int8.onnx   227 MB
  models\silero_vad.onnx                     1.7 MB
  videos\<视频名>\frames\*.jpg
  videos\<视频名>\transcript.txt
```

可用环境变量 `VIDEO_KIT` 改位置。

首次调用 `video_read` 若模型缺失会自动下载；想提前装好：

```powershell
python "%USERPROFILE%\.dsh\toolkits\video-kit\bin\setup.py"          # 安装
python "%USERPROFILE%\.dsh\toolkits\video-kit\bin\setup.py" --check  # 只体检
```

Python 依赖（`imageio-ffmpeg`、`yt-dlp`、`sherpa-onnx`、`websocket-client`）由脚本 `pip install --user` 装，不需要管理员权限，也不需要系统装 ffmpeg。

---

## 故障排查

| 现象 | 原因 | 解决 |
|---|---|---|
| **DSH 启动即崩：`Unexpected token '\uFEFF' ... is not valid JSON`** | `package.json` 被写成了带 BOM 的 UTF-8（PowerShell 5.1 的 `Set-Content -Encoding UTF8` 就是这个行为） | 用无 BOM 编码重写 `profiles/<profile>/package.json`；本安装器 1.1.1 起已强制无 BOM 并自检 |
| 新会话没有 `video_read` | 插件没加载 | 看 `~/.dsh/toolkits/video-kit/plugin-loaded.txt` 有没有本次启动的时间；没有就检查挂载块 |
| 老会话没有，新会话有 | 会话工具表冻结 | 正常行为，用新会话 |
| `register-error.txt` 出现 | 注册抛错 | 把文件内容发出来，一般是对应工具名已被占用 |
| 图片无法预览 | 附件缓存目录不可写 | 用 `copyTo` 指到工作区内 |
| `python 执行失败` | 没装 Python 或不在 PATH | 装 3.8+ 并确认 `python -V` 可用 |
| 转写为空 | 视频无音轨 / 纯音乐 | 正常，看帧即可 |
| 模型下载失败 | 网络 | 手动下 `model.int8.onnx` 与 `tokens.txt` 放进 `models\asr-paraformer-zh\` |

日志类标记文件都在数据目录：`plugin-loaded.txt`、`register-ok.txt`、`register-error.txt`。

---

## 卸载

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
# 连 230 MB 模型一起删：
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -PurgeData
```

---

## 目录结构

```
dsh-video-kit/
  index.js              插件入口（两个工具的注册与实现）
  cordis.patch.yml      bundle 形式的挂载声明
  bin/
    watch_video.py      下载 → 转写 → 抽帧
    discover.py         接管已登录浏览器，按关键词找候选（抖音/小红书/公众号）
    setup.py            依赖体检/安装
  extras/               研究辅助脚本（B站 WBI 搜索、CDP 嗅探等，插件不依赖）
  install.ps1
  uninstall.ps1
  README.md
  INSTALL.zh-CN.md
  LICENSE
```

---

## 许可

MIT。模型与第三方工具的许可各自遵循其上游（Paraformer / Silero VAD / ffmpeg / yt-dlp）。
