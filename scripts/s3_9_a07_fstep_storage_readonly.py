# -*- coding: utf-8 -*-
"""S3-9 · A-07 本体 · **F 步**真机 App 存储只读取证（一次可用）。

用途
----
在「HBuilderX 运行到手机 / 康迹 App」环境里，**直接读出** App 沙盒内的本地存储，
判定注销后 `kj:auth.*` 是否已全部清除（对应 S1-B §2.6 四触发清缓存契约）。

原理（实测确认，非推测）
------------------------
uni-app **App 端**的 `uni.setStorageSync` 落在应用私有的 **SQLite** 库里：

    /data/data/<包名>/databases/DCStorage        （表 DC_<hash>_storage，列 key/value/timestamp）

其中 `key` 就是 `utils/storage.js` 写入的 `kj:*` 全名（如 `kj:guide.agreement`）。
「HBuilderX 标准基座」是 debug 签名 ⇒ `adb shell run-as <包名>` 可直接读，**无需 root**。

性质
----
**严格只读**：只做 `cat`（读文件）；不安装、不启动、不停杀 App；
不写设备、不改产品代码、不发起任何网络请求。拉取到本地的副本仅用于解析。

用法
----
    python scripts/s3_9_a07_fstep_storage_readonly.py
    python scripts/s3_9_a07_fstep_storage_readonly.py --pkg io.dcloud.HBuilder
    python scripts/s3_9_a07_fstep_storage_readonly.py --adb <adb.exe 路径>

判据（与冻结契约逐条对齐）
--------------------------
  ① `kj:auth.access_token` / `kj:auth.refresh_token` / `kj:auth.user`
     / `kj:auth.profile_initialized` —— **必须不存在**（四个 auth 键）
  ② `kj:guide.agreement` —— **必须存在**（设备级状态，刻意不清除）
  ③ `kj:draft.*` / `kj:cache.*` / `kj:reminder.*` —— **必须不存在**（登录态域前缀）
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import io
import os
import sqlite3
import subprocess
import sys
import tempfile

# ── 默认 adb：HBuilderX 自带（多版本候选，取第一个存在的）────────────────────
ADB_CANDIDATES = [
    r"C:\Users\Toporder-WS\Downloads\HBuilderX.5.24.2026081301\HBuilderX"
    r"\plugins\launcher-tools\tools\adbs\adb.exe",
]
# 兜底：任意 HBuilderX 安装
ADB_GLOBS = [
    r"C:\**\HBuilderX\plugins\launcher-tools\tools\adbs\adb.exe",
    r"D:\**\HBuilderX\plugins\launcher-tools\tools\adbs\adb.exe",
    r"C:\Users\*\Downloads\HBuilderX*\HBuilderX\plugins\launcher-tools\tools\adbs\adb.exe",
]

DEFAULT_PKGS = ["io.dcloud.HBuilder", "com.kangji.healthtrack"]

AUTH_KEYS = [
    "auth.access_token", "auth.refresh_token", "auth.user", "auth.profile_initialized",
]
AUTH_PREFIXES = ["draft.", "cache.", "reminder."]
KEEP_KEY = "guide.agreement"

P = [0]
F = [0]


def w(s=""):
    print(s)


def ck(cond, label, detail=""):
    detail = "" if detail in ("", None) else str(detail)
    if cond:
        P[0] += 1
        w("  [PASS] %s%s" % (label, ("  | " + detail) if detail else ""))
    else:
        F[0] += 1
        w("  [FAIL] %s%s" % (label, ("  | " + detail) if detail else ""))
    return bool(cond)


def find_adb(explicit=None):
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    for p in ADB_CANDIDATES:
        if os.path.isfile(p):
            return p
    for pat in ADB_GLOBS:
        hits = glob.glob(pat, recursive=True)
        if hits:
            return sorted(hits)[0]
    # PATH 兜底
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(d, "adb.exe")
        if os.path.isfile(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adb", default=None, help="adb.exe 绝对路径（缺省自动探测 HBuilderX 自带）")
    ap.add_argument("--pkg", default=None, help="App 包名（缺省依次尝试 %s）" % DEFAULT_PKGS)
    ap.add_argument("--keep", action="store_true", help="保留拉取到本地的 DCStorage 副本")
    args = ap.parse_args()

    adb = find_adb(args.adb)
    w("=" * 88)
    w("A-07 本体 · F 步真机 App 存储只读取证（uni-app App 端 DCStorage）")
    w("=" * 88)
    ck(bool(adb), "① adb 可见（HBuilderX 自带）", str(adb))
    if not adb:
        w("\n未能定位 adb.exe；请用 --adb 指定，或确认 HBuilderX 已安装。")
        return 2

    def adb_raw(a, t=40):
        """直调 adb（**不加 shell**）—— 用于 devices / exec-out 等 adb 自身子命令。"""
        o = subprocess.run([adb] + list(a), capture_output=True, timeout=t)
        return (o.stdout.decode("utf-8", "replace") + o.stderr.decode("utf-8", "replace")).strip()

    def sh(a, t=40):
        """`adb shell <args>` 封装。"""
        o = subprocess.run([adb, "shell"] + list(a), capture_output=True, timeout=t)
        return (o.stdout.decode("utf-8", "replace") + o.stderr.decode("utf-8", "replace")).strip()

    # ── 设备 ──
    devs = [l for l in adb_raw(["devices", "-l"]).splitlines()[1:] if l.strip()]
    online = [l for l in devs if " device " in l]
    ck(bool(online), "② 真机在线（USB）", "; ".join(online)[:140])
    if not online:
        w("\n设备未连接或未授权 USB 调试。")
        return 3

    # ── 包名 ──
    pkgs = [args.pkg] if args.pkg else DEFAULT_PKGS
    chosen = None
    installed = sh(["pm", "list", "packages"])
    for p in pkgs:
        if ("package:%s" % p) in installed:
            chosen = p
            break
    ck(bool(chosen), "③ 定位到已安装的 App 包名", chosen or ("未找到；已在装包中含 dcloud=%s"
       % any("dcloud" in l.lower() for l in installed.splitlines())))
    if not chosen:
        w("\n请用 --pkg 明确指定包名。")
        return 4

    # ── run-as 可读性 ──
    who = sh(["run-as", chosen, "id"])
    ck("uid=" in who, "④ `run-as %s` 可读私有目录（标准基座为 debug 签名，无需 root）"
       % chosen, who[:80])
    if "uid=" not in who:
        w("\nread-only 通道不可用：请确认运行的是 HBuilderX 标准基座（debug 签名）而非正式包。")
        return 5

    priv = "/data/data/%s" % chosen
    # ── 定位 DCStorage ──
    lst = sh(["run-as", chosen, "ls", "-la", priv + "/databases/"])
    ck("DCStorage" in lst, "⑤ 定位 uni-app App 端存储库 databases/DCStorage",
       [l.split()[-1] for l in lst.splitlines() if "DCStorage" in l])

    # ── 拉取（只读 cat）──
    tmp = os.path.join(tempfile.gettempdir(), "DCStorage_%s.db" % chosen.replace(".", "_"))
    o = subprocess.run([adb, "exec-out", "run-as", chosen, "cat", priv + "/databases/DCStorage"],
                       capture_output=True, timeout=60)
    blob = o.stdout
    ck(len(blob) > 16 and blob[:15] == b"SQLite format 3",
       "⑥ DCStorage 成功只读拉取（SQLite 头校验）",
       "bytes=%d sha256_16=%s" % (len(blob),
                                  hashlib.sha256(blob).hexdigest()[:16] if blob else "-"))
    if not blob:
        return 6
    with open(tmp, "wb") as f:
        f.write(blob)

    # ── 解析 ──
    con = sqlite3.connect(tmp)
    cur = con.cursor()
    tabs = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    stor = [t for t in tabs if t.endswith("_storage")]
    ck(bool(stor), "⑦ 找到存储表 DC_*_storage", str(stor))

    rows = []
    for t in stor:
        rows += [dict(zip([d[0] for d in cur.description], r))
                 for r in cur.execute('SELECT key, value, timestamp FROM "%s"' % t).fetchall()]
    keys = [r["key"] for r in rows]
    w()
    w("  设备端存储键全清单（%d 条）：" % len(keys))
    for r in rows:
        w("    %-56s | %-28s | %s" % (r["key"][:56], str(r["value"])[:28], r["timestamp"]))
    w()

    kj = sorted(k for k in keys if k.startswith("kj:"))
    w("  其中 `kj:` 命名空间（本项目存储）共 %d 条：%s" % (len(kj), kj or "（无）"))
    w()

    # ── 判据 ──
    hit_auth = [k for k in kj if k[len("kj:"):] in AUTH_KEYS]
    ck(not hit_auth,
       "⑧ **`kj:auth.*` 四个键全部不存在**（登录态已清除）",
       "命中=%s" % (hit_auth or "无"))
    hit_pfx = [k for k in kj if any(k[len("kj:"):].startswith(p) for p in AUTH_PREFIXES)]
    ck(not hit_pfx,
       "⑨ **`kj:draft.*` / `kj:cache.*` / `kj:reminder.*` 全部不存在**（登录态域前缀已清）",
       "命中=%s" % (hit_pfx or "无"))
    ck(("kj:" + KEEP_KEY) in kj,
       "⑩ **`kj:guide.agreement` 仍存在**（设备级标记，契约要求**刻意保留**）",
       "存在" if ("kj:" + KEEP_KEY) in kj else "**缺失 ⇒ 清过头，属偏差**")

    # ── 原始字节取证（证明不是"从未写入"）──
    raw = blob
    w()
    w("  原始字节取证（含已删行的页内残留）：")
    for n in [b"kj:auth.access_token", b"kj:auth.refresh_token", b"kj:auth.user",
              b"kj:auth.profile_initialized", b"auth.refresh_token",
              b"profile_initialized", b"kj:guide.agreement"]:
        w("    %-30s 出现 %d 次" % (n.decode(), raw.count(n)))
    w("    freelist_count = %s（0 ⇒ 无空闲页）" % cur.execute("PRAGMA freelist_count").fetchone()[0])

    con.close()
    if not args.keep:
        try:
            os.remove(tmp)
        except OSError:
            pass
    else:
        w("\n  副本保留于：%s" % tmp)

    w()
    w("=" * 88)
    w("合计：PASS=%d  FAIL=%d   ⇒ %s" % (P[0], F[0], "PASS" if F[0] == 0 else "FAIL"))
    w("=" * 88)
    return 0 if F[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
