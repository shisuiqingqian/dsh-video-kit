# dsh-video-kit 安装说明（中文）

## 这是什么

给 DeepSeek Harness 增加"看视频"的能力。装好之后，直接对模型说：

> 用 video_read 读 D:\videos\会议录像.mp4

模型会自己拿到**带时间轴的逐字稿**和**一串关键帧图片**，然后逐帧看图、对着时间轴总结。不需要你先转码、先切图、先写提示词。

## 三步装好

**第一步：解压**

把 `dsh-video-kit.zip` 解压到任意位置（例如桌面），得到 `dsh-video-kit` 文件夹。

**第二步：运行安装脚本**

在文件夹里按住 Shift 点右键 → "在此处打开 PowerShell 窗口"，然后：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

看到 `=== 安装完成 ===` 就好了。

**第三步：重启 + 新开一个会话**

1. 完全退出 DeepSeek Harness（托盘也退），重新打开。
2. **新开一个会话**（重要：老会话看不到新工具，这是设计如此）。

然后在会话里问一句试试：

> 用 video_read 读 <你的视频路径>

第一次调用会自动下载语音识别模型（约 230 MB），等 1–3 分钟即可。之后都很快。

## 装之前可以先体检

```powershell
python "$env:USERPROFILE\.dsh\toolkits\video-kit\bin\setup.py" --check
```

## 常见问题

**问：装完了但是新会话里没有 video_read？**

看这个文件有没有刚刚的时间戳：

```
%USERPROFILE%\.dsh\toolkits\video-kit\plugin-loaded.txt
```

- 有 → 插件加载了，检查是不是新会话；同名工具冲突看 `register-error.txt`
- 没有 → 挂载没生效，检查 `%USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml` 末尾有没有 `tool-video-kit` 那三行

**问：图片显示"无法预览"？**

文件本身是好的，是会话的文件权限写不进附件缓存目录。调用时加一个工作区内的输出路径：

```
用 video_read 读 xxx.mp4，copyTo 传 C:\你的工作区\.frames
```

**问：会不会动我原来的配置？**

会改两处，都有备份：`cordis.patch.yml.bak-video-kit`、`package.json.bak-video-kit`。不想让它改配置，用 `-NoPatch` 只铺文件。

**问：怎么卸载？**

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
```

加 `-PurgeData` 会把 230 MB 模型一起删掉。

## 它支持什么输入

- 本地视频文件：mp4 / mov / mkv / webm / flv / m4a / mp3
- 网页链接：bilibili、YouTube、腾讯视频等 yt-dlp 支持的站点
- 需要登录/验证码的站点（抖音、小红书、快手、微博）抓不到，这是平台风控，不是工具问题

## 它不做什么

- 不做画面语义理解（它不认识"这是黑板"），画面内容由模型自己看图判断
- 不做音视频分离之外的剪辑
- 不上传任何数据到云端：转写在本机 CPU 上跑
