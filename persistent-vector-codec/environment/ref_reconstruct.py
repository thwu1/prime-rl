#!/usr/bin/env python3
import json, sys
def _r(data):
    B, BL = data["B"], data["BL"]
    M, L = 1 << B, 1 << BL
    lv = {e[0]: e[1] for e in data["leaves"]}
    iv = {e[0]: e[1] for e in data["inners"]}
    def tc(s):
        if s == 0: return 0
        if s <= L: return s
        r = s % L
        return r if r else L
    def dp(s):
        t = tc(s); b = s - t; n = b // L
        if n <= 0: return 0
        if n <= 1: return 1
        d, c = 1, M
        while c < n: c *= M; d += 1
        return d
    def tv(ni, d):
        el = []
        for ci in iv[ni]["children"]:
            el.extend(lv[ci] if d == 1 else tv(ci, d - 1))
        return el
    res = []
    for v in data["vectors"]:
        sz = v["size"]
        if sz == 0: res.append([]); continue
        tl = list(lv[v["tail"]]) if v["tail"] is not None else []
        if v["root"] is None: res.append(tl[:sz])
        else:
            d = dp(sz)
            res.append(tv(v["root"], d) + tl)
    return res
with open(sys.argv[1]) as f:
    print(json.dumps(_r(json.load(f))))
