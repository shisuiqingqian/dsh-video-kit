# -*- coding: utf-8 -*-
"""发现层：接管一个**你自己登录过**的 Edge，在抖音/小红书/公众号里按关键词找视频。

为什么这么做：这三个平台都要登录态，而且新版权 Chromium 不允许对默认 profile
开远程调试端口，所以这里用插件自己的独立 profile 目录——你在弹出的窗口里登录一次，
登录态（加密 cookie）就留在这个目录里，之后长期复用，插件不接触你的账号密码。

子命令：
  launch                     启动/复用专用浏览器窗口（有界面，可手动登录）
  status                     端口是否在、各平台是否已登录
  login    <platform>        打开该平台首页，等你自己登录
  search   <platform> <词>   搜索并返回候选视频列表（纯文本，不下载）

platform: douyin | xhs | weixin
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

EDGE = os.environ.get("VIDEO_EDGE") or r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DATA = os.environ.get("VIDEO_KIT") or os.path.join(
    os.path.expanduser("~"), ".dsh", "toolkits", "video-kit")
PROFILE = os.path.join(DATA, "browser")
PORT = int(os.environ.get("VIDEO_CDP_PORT") or 9333)

PLATFORMS = {
    "douyin": {
        "home": "https://www.douyin.com/",
        "search": "https://www.douyin.com/search/{q}?type=video",
        "cookies": ["sessionid", "sessionid_ss", "sid_tt"],
        "hit": 'a[href*="/video/"]',
    },
    "xhs": {
        "home": "https://www.xiaohongshu.com/explore",
        "search": "https://www.xiaohongshu.com/search_result?keyword={q}&type=video",
        "cookies": ["web_session"],
        "hit": 'a[href*="/explore/"], a[href*="/discovery/item/"]',
    },
    "weixin": {
        "home": "https://mp.weixin.qq.com/",
        "search": "https://mp.weixin.qq.com/cgi-bin/searchbiz?action=search_biz&query={q}",
        "cookies": ["slave_sid", "data_ticket", "bizuin"],
        "hit": 'a[href*="/s?"], a[href*="mp.weixin.qq.com/s"]',
    },
    # 冒烟测试用：不登录也能搜，验证 CDP 链路是否通
    "bilibili": {
        "home": "https://www.bilibili.com/",
        "search": "https://search.bilibili.com/all?keyword={q}",
        "cookies": [],
        "hit": 'a[href*="//www.bilibili.com/video/"], a[href*="/video/BV"]',
    },
}

# 从搜索结果卡片里抽字段：优先用 href / 标题 / 封面 alt，不依赖混淆过的 class 名
EXTRACT_JS = r"""
(function(){
  var sel = %(hit)s;
  var out = [], seen = {};
  var nodes = Array.from(document.querySelectorAll(sel));
  for (var i = 0; i < nodes.length; i++) {
    var a = nodes[i];
    var href = a.href || '';
    if (!href || seen[href]) continue;
    seen[href] = 1;
    var box = a;
    for (var k = 0; k < 4 && box.parentElement; k++) {
      if ((box.innerText || '').trim().length > 6) break;
      box = box.parentElement;
    }
    var title = (a.getAttribute('title') || '').trim();
    if (!title) {
      var img = a.querySelector('img');
      if (img) title = (img.getAttribute('alt') || '').trim();
    }
    if (!title) {
      var t = (a.innerText || '').trim();
      if (t) title = t.split('\n')[0];
    }
    var text = (box.innerText || '').replace(/\s+/g, ' ').trim();
    if (!title && !text) continue;
    out.push({ url: href, title: title.slice(0, 120), snippet: text.slice(0, 160) });
    if (out.length >= %(limit)d) break;
  }
  return JSON.stringify({ title: document.title, count: out.length, items: out });
})()
"""

LOGIN_STATE_JS = r"""
(function(){
  var t = document.body ? document.body.innerText : '';
  return JSON.stringify({
    url: location.href,
    title: document.title,
    hasLoginWord: /登录|登入|扫码/.test(t.slice(0, 2000)),
    textLen: t.length
  });
})()
"""


# ---------------------------------------------------------------- CDP 基座
def alive():
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/json/version" % PORT, timeout=1).read()
        return True
    except Exception:
        return False


def launch(url="about:blank", wait=25, hidden=False):
    """启动专用 Edge。hidden=True 时窗口移到屏幕外——不打扰你，但不是 headless，网站照样当真浏览器。已在跑就直接返回。"""
    if alive():
        return {"ok": True, "action": "already-running", "port": PORT, "profile": PROFILE}
    if not os.path.exists(EDGE):
        raise SystemExit("找不到 Edge：%s（可用环境变量 VIDEO_EDGE 指定）" % EDGE)
    os.makedirs(PROFILE, exist_ok=True)
    args = [
        EDGE,
        "--remote-debugging-port=%d" % PORT,
        "--user-data-dir=%s" % PROFILE,
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=msEdgeSidebarV2",
    ]
    if hidden:
        args += ["--window-position=-32000,-32000", "--window-size=1280,900"]
    else:
        args += ["--window-position=240,140", "--window-size=1400,1000"]
    args.append(url)
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(int(wait * 2)):
        if alive():
            return {"ok": True, "action": "launched", "port": PORT, "profile": PROFILE}
        time.sleep(0.5)
    raise SystemExit("Edge 没能在 %d 秒内开起调试端口" % wait)


def tabs():
    raw = urllib.request.urlopen("http://127.0.0.1:%d/json/list" % PORT, timeout=5).read()
    return json.loads(raw.decode())


def new_tab(url):
    req = urllib.request.Request(
        "http://127.0.0.1:%d/json/new?%s" % (PORT, urllib.parse.quote(url, safe="")),
        method="PUT")
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())


class Tab:
    """一个页签的 CDP 会话：只做 evaluate / navigate / cookies 这几件事。"""

    def __init__(self, ws_url):
        import websocket
        self.ws = websocket.create_connection(ws_url, timeout=40, suppress_origin=True)
        self.mid = 0

    def call(self, method, params=None, timeout=40):
        import websocket
        self.mid += 1
        mine = self.mid
        self.ws.send(json.dumps({"id": mine, "method": method, "params": params or {}}))
        end = time.time() + timeout
        self.ws.settimeout(5)
        while time.time() < end:
            try:
                msg = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break
            if msg.get("id") == mine:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message") or str(msg["error"]))
                return msg.get("result", {})
        return {}

    def evaluate(self, expr, timeout=40):
        r = self.call("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": False,
            "userGesture": True}, timeout)
        return (r.get("result") or {}).get("value")

    def goto(self, url, settle=3.0):
        self.call("Page.enable")
        self.call("Page.navigate", {"url": url})
        end = time.time() + settle
        while time.time() < end:
            time.sleep(0.4)
            try:
                if self.evaluate("document.readyState") == "complete":
                    break
            except Exception:
                pass
        time.sleep(1.0)

    def cookies(self):
        r = self.call("Network.getAllCookies", timeout=15)
        return [c.get("name") for c in (r.get("cookies") or [])]

    def scroll(self, times=3):
        for _ in range(times):
            try:
                self.evaluate("window.scrollBy(0, 900)")
            except Exception:
                pass
            time.sleep(0.9)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def open_tab(url, settle=3.0, hidden=False):
    launch(hidden=hidden)
    if not url or url == "about:blank":
        t = new_tab("about:blank")
    else:
        t = new_tab(url)
    tab = Tab(t["webSocketDebuggerUrl"])
    if url and url != "about:blank":
        tab.goto(url, settle=settle)
    return tab


# ---------------------------------------------------------------- 子命令
def cmd_launch(args):
    r = launch(args.url or "about:blank")
    print(json.dumps(r, ensure_ascii=False))
    return 0


def cmd_status(args):
    if not alive():
        print(json.dumps({"ok": False, "action": "not-running", "port": PORT,
                          "hint": "先运行 discover.py launch"}, ensure_ascii=False))
        return 0
    tab = open_tab("about:blank", hidden=True)
    names = set(tab.cookies())
    out = {"ok": True, "port": PORT, "profile": PROFILE, "platforms": {}}
    for name, cfg in PLATFORMS.items():
        need = cfg.get("cookies") or []
        hit = [c for c in need if c in names]
        out["platforms"][name] = {
            "loggedIn": bool(hit) if need else None,
            "matchedCookies": hit,
            "needCookies": need,
        }
    tab.close()
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_login(args):
    cfg = PLATFORMS[args.platform]
    tab = open_tab(cfg["home"], settle=4.0)
    names = set(tab.cookies())
    hit = [c for c in cfg["cookies"] if c in names]
    tab.close()
    print(json.dumps({
        "ok": True, "platform": args.platform, "loggedIn": bool(hit), "matchedCookies": hit,
        "hint": "浏览器窗口已打开，请在里面完成登录；登录后重新运行 status 确认",
    }, ensure_ascii=False))
    return 0


def cmd_search(args):
    cfg = PLATFORMS[args.platform]
    url = cfg["search"].format(q=urllib.parse.quote(args.query, safe=""))
    tab = open_tab(url, settle=args.settle, hidden=True)
    state = json.loads(tab.evaluate(LOGIN_STATE_JS) or "{}")
    names = set(tab.cookies())
    hit = [c for c in cfg.get("cookies") or [] if c in names]
    if args.scroll:
        tab.scroll(args.scroll)
    raw = tab.evaluate(EXTRACT_JS % {
        "hit": json.dumps(cfg["hit"]), "limit": int(args.limit)}, timeout=30)
    tab.close()
    try:
        data = json.loads(raw or "{}")
    except Exception:
        data = {"title": "", "count": 0, "items": []}
    need = cfg.get("cookies") or []
    payload = {
        "ok": True,
        "platform": args.platform,
        "query": args.query,
        "searchUrl": url,
        "loggedIn": bool(hit) if need else None,
        "pageTitle": data.get("title") or state.get("title") or "",
        "count": len(data.get("items") or []),
        "items": data.get("items") or [],
    }
    if need and not hit:
        payload["warning"] = "未检测到登录态，结果可能为空或触发登录墙"
    if not payload["items"]:
        payload["warning"] = (payload.get("warning", "") +
                              " 页面未解析到结果：可能被登录墙/验证码拦住，或选择器需更新").strip()
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("launch")
    p.add_argument("--url", default="about:blank")
    p.set_defaults(fn=cmd_launch)

    p = sub.add_parser("status")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("login")
    p.add_argument("platform", choices=list(PLATFORMS))
    p.set_defaults(fn=cmd_login)

    p = sub.add_parser("search")
    p.add_argument("platform", choices=list(PLATFORMS))
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--scroll", type=int, default=2)
    p.set_defaults(fn=cmd_search)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
