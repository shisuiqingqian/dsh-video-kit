# -*- coding: utf-8 -*-
"""bilibili WBI 签名搜索（无需登录）：api.bilibili.com/x/web-interface/search/type"""
import sys, json, hashlib, time, urllib.parse, http.cookiejar, urllib.request

sys.stdout.reconfigure(encoding="utf-8")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
             33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
             61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62,
             11, 36, 20, 34, 44, 52]

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def get(url, referer="https://www.bilibili.com/"):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": referer, "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9"})
    return op.open(req, timeout=25).read().decode("utf-8", "replace")


def init_cookie():
    try:
        get("https://www.bilibili.com/")
    except Exception as e:
        print("[cookie]", e)


def keys():
    j = json.loads(get("https://api.bilibili.com/x/web-interface/nav"))
    w = j["data"]["wbi_img"]
    img = w["img_url"].rsplit("/", 1)[-1].split(".")[0]
    sub = w["sub_url"].rsplit("/", 1)[-1].split(".")[0]
    raw = img + sub
    return "".join(raw[i] for i in MIXIN_TAB)[:32]


def sign(params, mk):
    params["wts"] = int(time.time())
    items = sorted(params.items())
    q = urllib.parse.urlencode([(k, str(v)) for k, v in items],
                               quote_via=urllib.parse.quote)
    params["w_rid"] = hashlib.md5((q + mk).encode()).hexdigest()
    return params


def search(kw, page=1):
    mk = keys()
    p = sign({"search_type": "video", "keyword": kw, "page": page,
              "page_size": 10, "order": "totalrank"}, mk)
    url = "https://api.bilibili.com/x/web-interface/wbi/search/type?" + \
          urllib.parse.urlencode(p, quote_via=urllib.parse.quote)
    j = json.loads(get(url, referer="https://search.bilibili.com/"))
    if j.get("code") != 0:
        print("[api]", j.get("code"), j.get("message"))
        return []
    out = []
    for r in j["data"].get("result") or []:
        out.append({
            "bvid": r.get("bvid"),
            "title": (r.get("title") or "").replace("<em class=\"keyword\">", "")
                                             .replace("</em>", ""),
            "author": r.get("author"),
            "dur": r.get("duration"),
            "play": r.get("play"),
            "pub": time.strftime("%Y-%m-%d", time.localtime(r.get("pubdate", 0))),
        })
    return out


if __name__ == "__main__":
    init_cookie()
    for kw in sys.argv[1:]:
        print("=" * 8, kw)
        for it in search(kw):
            print("%s | %-4s | %-7s | %s | %s | %s" % (
                it["bvid"], it["dur"], it["play"], it["author"], it["pub"], it["title"]))
