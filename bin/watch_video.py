# -*- coding: utf-8 -*-
"""看视频：下载 → 抽音转写 → 抽关键帧。
用法：
  python watch_video.py <url 或本地文件> [--every 20] [--maxframes 24]
产出 tools/videos/<slug>/ :
  video.*        原视频
  transcript.txt 带时间轴的逐字稿（sherpa-onnx paraformer-zh）
  frames/f_*.jpg 关键帧，可用 read_image 直接看
"""
import sys, os, json, re, subprocess, glob, wave
sys.stdout.reconfigure(encoding="utf-8")

KIT = os.environ.get("VIDEO_KIT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VID = os.path.join(KIT, "videos")
ASR = os.path.join(KIT, "models", "asr-paraformer-zh")
VAD = os.path.join(KIT, "models", "silero_vad.onnx")

import imageio_ffmpeg
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def slug(s):
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", s)[-60:].strip("_")
    return s or "video"


def download(url, outdir):
    out = os.path.join(outdir, "video.%(ext)s")
    r = run([sys.executable, "-m", "yt_dlp", "--no-warnings", "-f",
             "best[height<=720]/best", "--no-playlist", "-o", out, url])
    print("[yt-dlp] rc=%d" % r.returncode)
    if r.returncode != 0:
        print(r.stdout[-1200:], r.stderr[-2000:])
    return sorted(glob.glob(os.path.join(outdir, "video.*")))


def duration(path):
    r = run([FFMPEG, "-i", path, "-f", "null", "-"])
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr or "")
    if m:
        h, mi, s = m.groups()
        return int(h) * 3600 + int(mi) * 60 + float(s)
    return 0.0


def to_wav(path, outdir):
    wav = os.path.join(outdir, "audio16k.wav")
    run([FFMPEG, "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
         "-acodec", "pcm_s16le", wav])
    return wav if os.path.exists(wav) else None


def transcribe(wav, outdir):
    import sherpa_onnx
    model = os.path.join(ASR, "model.int8.onnx")
    tokens = os.path.join(ASR, "tokens.txt")
    if not (os.path.exists(model) and os.path.exists(tokens)):
        print("[asr] model missing"); return ""
    rec = sherpa_onnx.OfflineRecognizer.from_paraformer(
        paraformer=model, tokens=tokens, num_threads=2, sample_rate=16000,
        feature_dim=80, decoding_method="greedy_search", debug=False)
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = VAD
    cfg.silero_vad.min_silence_duration = 0.25
    cfg.silero_vad.min_speech_duration = 0.25
    cfg.silero_vad.max_speech_duration = 20
    cfg.sample_rate = 16000
    cfg.num_threads = 2
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)

    wf = wave.open(wav, "rb")
    assert wf.getframerate() == 16000
    n = 512
    total = 0
    lines = []
    while True:
        data = wf.readframes(n)
        if not data:
            break
        samples = [x / 32768.0 for x in range(0)]  # placeholder
        import array
        a = array.array("h", data)
        samples = [v / 32768.0 for v in a]
        vad.accept_waveform(samples)
        total += len(samples)
        while not vad.empty():
            seg = vad.front
            st = seg.start / 16000.0
            s = rec.create_stream()
            s.accept_waveform(16000, seg.samples)
            rec.decode_stream(s)
            txt = s.result.text.replace(" ", "")
            if txt.strip():
                lines.append((st, txt))
            vad.pop()
    vad.flush()
    while not vad.empty():
        seg = vad.front
        s = rec.create_stream()
        s.accept_waveform(16000, seg.samples)
        rec.decode_stream(s)
        txt = s.result.text.replace(" ", "")
        if txt.strip():
            lines.append((seg.start / 16000.0, txt))
        vad.pop()

    out = []
    for st, txt in lines:
        out.append("[%02d:%02d] %s" % (int(st) // 60, int(st) % 60, txt))
    body = "\n".join(out)
    with open(os.path.join(outdir, "transcript.txt"), "w", encoding="utf-8") as f:
        f.write(body)
    return body


def frames(path, outdir, every, maxframes):
    fd = os.path.join(outdir, "frames")
    os.makedirs(fd, exist_ok=True)
    for f in glob.glob(os.path.join(fd, "*.jpg")):
        os.remove(f)
    dur = duration(path)
    if not dur:
        dur = every * maxframes
    step = every
    if dur / every + 1 > maxframes:
        step = dur / maxframes
    n = min(maxframes, int(dur / step) + 1)
    for i in range(n):
        t = min(max(0.0, dur - 0.3), i * step)
        dst = os.path.join(fd, "f_%03d.jpg" % i)
        run([FFMPEG, "-y", "-ss", "%.2f" % t, "-i", path, "-frames:v", "1",
             "-vf", "scale=1280:-2", "-q:v", "3", dst])
        if os.path.exists(dst):
            print("[frame] %6.1fs -> %s" % (t, os.path.basename(dst)))
    return fd


def looks_like_path(s):
    return bool(re.match(r"^[A-Za-z]:[\\/]", s)) or s.startswith("\\\\")


def hint_missing(path):
    parent = os.path.dirname(path)
    print("ERROR 本地文件不存在: %s" % path)
    if parent and os.path.isdir(parent):
        same = [f for f in os.listdir(parent)
                if os.path.splitext(f)[0] == os.path.splitext(os.path.basename(path))[0]]
        if same:
            print("  同目录下有同名不同扩展名的文件: %s" % ", ".join(same))
        cands = [f for f in os.listdir(parent) if f.lower().endswith(
            (".mp4", ".mov", ".mkv", ".flv", ".webm", ".m4v"))]
        if cands:
            print("  该目录下的视频文件（前10个）:")
            for f in cands[:10]:
                print("    " + os.path.join(parent, f))
    print("  提示: source 必须是【视频文件本身】的绝对路径，不能是目录。")


def main():
    src = sys.argv[1]
    every, maxframes = 20.0, 24
    every_given = "--every" in sys.argv
    if every_given:
        every = float(sys.argv[sys.argv.index("--every") + 1])
    if "--maxframes" in sys.argv:
        maxframes = int(sys.argv[sys.argv.index("--maxframes") + 1])

    if os.path.exists(src):
        if os.path.isdir(src):
            print("ERROR source 是目录，不是视频文件: %s" % src)
            vids = [f for f in os.listdir(src) if f.lower().endswith(
                (".mp4", ".mov", ".mkv", ".flv", ".webm", ".m4v"))]
            if vids:
                print("  该目录里的视频：")
                for f in vids[:10]:
                    print("    " + os.path.join(src, f))
            else:
                subs = [d for d in os.listdir(src) if os.path.isdir(os.path.join(src, d))]
                if subs:
                    print("  该目录下的子目录（可能是输出目录，里面的 frames/ 是帧图）：%s" % ", ".join(subs[:8]))
                print("  提示：输出目录里只有 transcript.txt 和 frames/，原视频不在其中；请把 source 指向视频文件本身。")
            return
        outdir = os.path.join(VID, slug(os.path.splitext(os.path.basename(src))[0]))
        os.makedirs(outdir, exist_ok=True)
        path = src
    elif looks_like_path(src):
        hint_missing(src)
        return
    else:
        outdir = os.path.join(VID, slug(src))
        os.makedirs(outdir, exist_ok=True)
        files = download(src, outdir)
        if not files:
            print("ERROR 下载失败: %s" % src)
            print("  若这是本地路径，请确认文件存在；若是链接，请确认平台受支持且有访问权限。")
            return
        path = files[0]

    dur = duration(path)
    print("OUTDIR:", outdir)
    print("VIDEO:", path, "dur=%.1fs" % dur)
    # 短视频自动加密抽帧，避免默认 20 秒间隔只出 1 张
    if not every_given and 0 < dur <= 40:
        every = max(1.0, dur / 10.0)
        print("AUTO every=%.1fs（视频仅 %.1fs，已自动加密抽帧）" % (every, dur))
    wav = to_wav(path, outdir)
    if wav:
        print("=== TRANSCRIPT ===")
        print(transcribe(wav, outdir))
    print("FRAMES:", frames(path, outdir, every, maxframes))


if __name__ == "__main__":
    main()
