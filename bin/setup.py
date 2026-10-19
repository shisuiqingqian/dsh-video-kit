# -*- coding: utf-8 -*-
"""dsh-video-kit 运行时自举：把视频读取所需的 python 依赖与 ASR 模型装到位。

为什么需要它：模型 227 MB、ffmpeg 61 MB 进不了 npm/GitHub 包（单包上限），
所以插件只带代码，第一次真正用时再按需下载到数据目录。

用法：
  python setup.py            # 缺什么装什么（幂等，已就绪则秒过）
  python setup.py --check    # 只体检，不做任何改动

数据目录（可用环境变量 VIDEO_KIT 覆盖）：
  ~/.dsh/toolkits/video-kit/
    models/asr-paraformer-zh/model.int8.onnx
    models/asr-paraformer-zh/tokens.txt
    models/silero_vad.onnx
    videos/                  # 每个视频一个子目录（下载、wav、逐字稿、关键帧）

最后一行输出 JSON 状态，供 index.js 解析。
"""
import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

# Windows 控制台默认 cp936/GBK，中文提示会变乱码；统一按 UTF-8 输出，失败就算了。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DATA = os.environ.get("VIDEO_KIT") or os.path.join(
    os.path.expanduser("~"), ".dsh", "toolkits", "video-kit")
MODELS = os.path.join(DATA, "models")
ASR_DIR = os.path.join(MODELS, "asr-paraformer-zh")
ASR_MODEL = os.path.join(ASR_DIR, "model.int8.onnx")
ASR_TOKENS = os.path.join(ASR_DIR, "tokens.txt")
VAD = os.path.join(MODELS, "silero_vad.onnx")

# 判「装好了」的体积下限：真模型 227 MB / tokens 75 KB，低于这个数就是错误页或半截文件
MIN_MODEL = 100_000_000
MIN_TOKENS = 10_000

# 依赖：包名 -> import 名
PKGS = [
    ("imageio-ffmpeg", "imageio_ffmpeg"),
    ("yt-dlp", "yt_dlp"),
    ("sherpa-onnx", "sherpa_onnx"),
    ("websocket-client", "websocket"),
]

ASR_TARBALL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
               "asr-models/sherpa-onnx-paraformer-zh-2023-09-14.tar.bz2")
ASR_HF = ("https://hf-mirror.com/csukuangfj/"
          "sherpa-onnx-paraformer-zh-2023-09-14/resolve/main/")
VAD_URLS = [
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
    "https://hf-mirror.com/csukuangfj/sherpa-onnx-silero-vad/resolve/main/silero_vad.onnx",
]
UA = {"User-Agent": "dsh-video-kit/0.2 (+https://github.com/)"}


def log(msg):
    print("[setup] %s" % msg, flush=True)


def fetch(url, dest, expect_min=1024):
    """下载到 dest；边下边回调进度。失败抛异常，由调用方换下一个镜像。"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        step = 16 * 1024 * 1024
        mark = 0
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if done - mark >= step or (total and done >= total):
                mark = done
                pct = ("%d%%" % (done * 100 // total)) if total else "?"
                log("  %s  %.1f MB / %.1f MB  (%s)" % (
                    os.path.basename(dest), done / 1e6,
                    (total / 1e6) if total else 0, pct))
    size = os.path.getsize(tmp)
    if size < expect_min:
        os.remove(tmp)
        raise RuntimeError("下载内容过小：%d 字节，疑似失败页" % size)
    os.replace(tmp, dest)
    log("  -> %s (%.1f MB)" % (dest, size / 1e6))


def deps_state():
    out = {}
    for pkg, mod in PKGS:
        try:
            __import__(mod)
            out[pkg] = True
        except Exception:
            out[pkg] = False
    return out


def install_deps(missing):
    log("安装 python 依赖：%s" % ", ".join(missing))
    cmds = [
        [sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check"] + missing,
        [sys.executable, "-m", "pip", "install", "--user",
         "--disable-pip-version-check"] + missing,
    ]
    last = None
    for cmd in cmds:
        log(" ".join(cmd[:6]) + " ...")
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            return True, r.stdout[-1500:]
        last = (r.stdout or "")[-1500:] + (r.stderr or "")[-1500:]
    return False, last or "pip 失败且无输出"


def ensure_vad():
    if os.path.exists(VAD) and os.path.getsize(VAD) > 100_000:
        return True
    for url in VAD_URLS:
        try:
            log("下载 VAD 模型：%s" % url)
            fetch(url, VAD, expect_min=100_000)
            return True
        except Exception as e:
            log("  失败：%s" % e)
    return False


def _valid_asr():
    """两个文件都在且体积像真模型，才算装好（挡住错误页、半截文件）。"""
    try:
        return (os.path.getsize(ASR_MODEL) >= MIN_MODEL
                and os.path.getsize(ASR_TOKENS) >= MIN_TOKENS)
    except OSError:
        return False


def _extract_member(tf, member, dest_dir):
    """把指定成员解到 dest_dir，拍平目录层级。

    不用 tarfile 的 filter= 参数：那是 Python 3.12+（或 3.11.4+）才有的，
    3.8/3.9 直接 TypeError；也不用改 m.name 后 extract（容易写出错内容）。
    """
    try:
        src = tf.extractfile(member)
        if src is None:
            return None
    except Exception:
        return None
    target = os.path.join(dest_dir, os.path.basename(member.name))
    with src, open(target, "wb") as out:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    return target


def ensure_asr():
    if _valid_asr():
        return True
    os.makedirs(ASR_DIR, exist_ok=True)
    # 首选官方 release 压缩包（一次拿全 model + tokens）
    try:
        log("下载 ASR 模型包：%s" % ASR_TARBALL)
        with tempfile.TemporaryDirectory() as td:
            tar_path = os.path.join(td, "asr.tar.bz2")
            fetch(ASR_TARBALL, tar_path, expect_min=50_000_000)
            want = ("model.int8.onnx", "tokens.txt")
            with tarfile.open(tar_path, "r:bz2") as tf:
                for m in tf.getmembers():
                    if not m.isfile():
                        continue
                    base = os.path.basename(m.name)
                    if base in want:
                        got = _extract_member(tf, m, ASR_DIR)
                        if got:
                            log("  解出 %s（%d 字节）" % (base, os.path.getsize(got)))
        if _valid_asr():
            return True
        log("解包结果不完整，转兜底下载")
    except Exception as e:
        log("模型包下载/解包失败：%s" % e)
    # 兜底：直接拉两个文件
    try:
        fetch(ASR_HF + "model.int8.onnx", ASR_MODEL, expect_min=MIN_MODEL)
        fetch(ASR_HF + "tokens.txt", ASR_TOKENS, expect_min=MIN_TOKENS)
        if _valid_asr():
            return True
    except Exception as e:
        log("兜底下载也失败：%s" % e)
    # 收拾残局：别把半截文件留下让下次误判为已装
    for p, need in ((ASR_MODEL, MIN_MODEL), (ASR_TOKENS, MIN_TOKENS)):
        try:
            if os.path.exists(p) and os.path.getsize(p) < need:
                os.remove(p)
        except OSError:
            pass
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只体检，不安装")
    a = ap.parse_args()

    os.makedirs(MODELS, exist_ok=True)
    os.makedirs(os.path.join(DATA, "videos"), exist_ok=True)

    state = {"data_dir": DATA, "deps": {}, "models": {}, "ok": False, "action": "check" if a.check else "ensure"}

    deps = deps_state()
    missing = [p for p, ok in deps.items() if not ok]
    if missing and not a.check:
        ok, tail = install_deps(missing)
        if not ok:
            state["error"] = "pip 安装失败：" + tail
        deps = deps_state()
    state["deps"] = deps

    asr_ok = _valid_asr()
    vad_ok = os.path.exists(VAD) and os.path.getsize(VAD) > 100_000
    if not a.check:
        if not asr_ok:
            asr_ok = ensure_asr()
        if not vad_ok:
            vad_ok = ensure_vad()
    state["models"] = {"asr": asr_ok, "vad": vad_ok}
    state["ok"] = bool(all(deps.values()) and asr_ok and vad_ok)
    if state["ok"]:
        state["action"] = "ready"
    log("状态：deps=%s models=%s" % (deps, state["models"]))
    print(json.dumps(state, ensure_ascii=False))
    return 0 if state["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
