# -*- coding: utf-8 -*-
"""CDP 网络嗅探：用无头 Edge 打开任意页面，抓取真实视频请求（mp4/m3u8/playwm 等）。
用法： python cdp_sniff.py "<url>" [秒数]
输出： 打印所有媒体 URL + 页面标题 + 最终 DOM 里的 video src
"""
import sys, json, time, subprocess, urllib.request, os, tempfile, re

sys.stdout.reconfigure(encoding="utf-8")

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9333
MEDIA = re.compile(r"(\.mp4|\.m3u8|\.flv|playwm|playaddr|video/tos|/video/|\.ts\?)", re.I)
SKIP = re.compile(r"(\.jpg|\.png|\.webp|\.gif|\.css|\.js$|\.woff|\.ico)", re.I)


def start():
    prof = os.path.join(tempfile.gettempdir(), "edge_cdp_prof")
    p = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                          "--no-default-browser-check", "--mute-audio",
                          "--autoplay-policy=no-user-gesture-required",
                          f"--remote-debugging-port={PORT}",
                          f"--user-data-dir={prof}", "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1).read()
            return p
        except Exception:
            time.sleep(0.5)
    raise SystemExit("edge cdp not ready")


def new_tab(url):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?{urllib.parse.quote(url, safe='')}",
                                 method="PUT")
    return json.loads(urllib.request.urlopen(req, timeout=10).read().decode())


def main():
    url = sys.argv[1]
    wait = float(sys.argv[2]) if len(sys.argv) > 2 else 15
    import websocket
    proc = start()
    tab = new_tab(url)
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30,
                                     suppress_origin=True)
    mid = [0]

    def call(method, params=None):
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
        return mid[0]

    call("Network.enable")
    call("Page.enable")
    found = {}
    end = time.time() + wait
    ws.settimeout(2)
    while time.time() < end:
        try:
            msg = json.loads(ws.recv())
        except Exception:
            continue
        m = msg.get("method")
        if m in ("Network.requestWillBeSent", "Network.responseReceived"):
            r = msg["params"].get("request") or msg["params"].get("response") or {}
            u = r.get("url", "")
            if u and MEDIA.search(u) and not SKIP.search(u):
                found[u] = r.get("mimeType") or r.get("type") or ""
    # 取页面标题与 video 标签
    call("Runtime.evaluate", {"expression":
         "document.title + ' ||| ' + Array.from(document.querySelectorAll('video')).map(v=>v.src||v.currentSrc).join(' ; ')",
         "returnByValue": True})
    title = dom = ""
    t0 = time.time()
    while time.time() - t0 < 6:
        try:
            msg = json.loads(ws.recv())
        except Exception:
            continue
        if msg.get("id") == mid[0]:
            title = (msg.get("result", {}).get("result", {}) or {}).get("value", "")
            break
    print("PAGE:", title[:300])
    print("MEDIA URLS (%d):" % len(found))
    for u, mt in found.items():
        print(" ", u[:260], "|", mt)
    ws.close()
    try:
        proc.terminate()
    except Exception:
        pass


if __name__ == "__main__":
    import urllib.parse
    main()
