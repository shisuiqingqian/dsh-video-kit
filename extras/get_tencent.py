# -*- coding: utf-8 -*-
import sys, json, re, subprocess, os
sys.stdout.reconfigure(encoding="utf-8")
W = r"C:\Users\23038\Documents\deepseek-harness\video-kit\bin"
raw = open(os.path.join(W, "gi_i3357z3xh5r.json"), "rb").read().decode("utf-8", "replace")
raw = raw.strip()
raw = re.sub(r"^QZOutputJson=", "", raw).rstrip(";")
o = json.loads(raw)
vi = o["vl"]["vi"][0]
fn = vi["fn"]; keyid = vi.get("keyid", ""); vkey = vi["fvkey"]
uis = [u["url"] for u in vi["ul"]["ui"]]
print("fn:", fn)
print("keyid:", keyid)
print("duration:", vi.get("td"), "fs:", vi.get("fs"))
cands = []
base = uis[0]
cands.append(base + fn + "?vkey=" + vkey)
cands.append(base + keyid + "?vkey=" + vkey)
cands.append(base + fn)
for i, u in enumerate(cands):
    out = os.path.join(W, "vids", "yiheyuan_try%d.mp4" % i)
    r = subprocess.run(["curl.exe", "-s", "-L", "--max-time", "180", "-A",
                        "Mozilla/5.0", "-H", "Referer: https://v.qq.com/",
                        "-o", out, "-w", "%{http_code} %{size_download}", u],
                       capture_output=True, text=True)
    size = os.path.getsize(out) if os.path.exists(out) else 0
    print(i, r.stdout.strip(), "bytes=", size, u[:90])
    if size > 200000:
        print("OK ->", out)
        break
