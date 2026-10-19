# -*- coding: utf-8 -*-
"""鏃犲ご Edge 鎵撳紑椤甸潰骞舵墽琛?JS锛屾墦鍗扮粨鏋溿€?鐢ㄦ硶锛?python cdp_eval.py "<url>" "<js琛ㄨ揪寮?" [绛夊緟绉掓暟]
"""
import sys, json, time, subprocess, urllib.request, urllib.parse, os, tempfile

sys.stdout.reconfigure(encoding="utf-8")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9334


def start():
    prof = os.path.join(tempfile.gettempdir(), "edge_cdp_prof2")
    p = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                          "--mute-audio", f"--remote-debugging-port={PORT}",
                          f"--user-data-dir={prof}", "--window-size=1440,900", "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1).read()
            return p
        except Exception:
            time.sleep(0.5)
    raise SystemExit("cdp not ready")


def main():
    url = sys.argv[1]
    expr = sys.argv[2]
    if expr.startswith('file:'):
        expr = open(expr[5:], encoding='utf-8').read()
    wait = float(sys.argv[3]) if len(sys.argv) > 3 else 12
    import websocket
    proc = start()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/json/new?{urllib.parse.quote(url, safe='')}", method="PUT")
    tab = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=40, suppress_origin=True)
    i = [0]

    def send(method, params=None):
        i[0] += 1
        ws.send(json.dumps({"id": i[0], "method": method, "params": params or {}}))
        return i[0]

    send("Page.enable")
    send("Runtime.enable")
    time.sleep(wait)
    target = send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                       "awaitPromise": True})
    out = None
    ws.settimeout(2)
    end = time.time() + 25
    while time.time() < end:
        try:
            msg = json.loads(ws.recv())
        except Exception:
            continue
        if msg.get("id") == target:
            out = msg
            break
    if out and "result" in out:
        val = out["result"].get("result", {}).get("value")
        print(val if isinstance(val, str) else json.dumps(val, ensure_ascii=False, indent=1))
    else:
        print("EVAL FAILED", json.dumps(out, ensure_ascii=False)[:800])
    ws.close()
    try:
        proc.terminate()
    except Exception:
        pass


if __name__ == "__main__":
    main()

