#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-command setup for bilibili-video-notes.

Rules that keep installation fast on a fresh machine:
  * never download a browser binary; the skill reuses the system Chrome/Edge;
  * offline wheels in wheels/ win over the network;
  * every network attempt has a hard timeout, so it never hangs silently;
  * --doctor works with zero third-party dependencies.
"""
import argparse
import os
import platform
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WHEELS = ROOT / "wheels"
REQUIREMENTS = ROOT / "requirements.txt"
MIRRORS = (
    "https://pypi.org/simple",
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple",
)


def version_of(name):
    try:
        from importlib import metadata
        return metadata.version(name)
    except Exception:
        return None


def browser_channel():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from browser_subtitles import detect_browser_channel
        return detect_browser_channel()
    except Exception:
        return None


def inspect():
    return {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "playwright": version_of("playwright"),
        "pyee": version_of("pyee"),
        "greenlet": version_of("greenlet"),
        "deps_ready": verify(),
        "browser_channel": browser_channel(),
        "offline_wheels": sorted(p.name for p in WHEELS.glob("*.whl")),
    }


def show(report):
    print("Python      : " + report["python"])
    print("解释器路径  : " + report["python_executable"])
    print("提示        : 安装依赖与运行 fetch/login 必须是同一个解释器。")
    for name in ("playwright", "pyee", "greenlet"):
        print("%-11s : %s" % (name, report[name] or "missing"))
    print("依赖状态    : %s" % ("可导入，已就绪" if report["deps_ready"] else "不可导入，需要安装"))
    if not report["deps_ready"] and all(report[k] for k in ("playwright", "pyee", "greenlet")):
        print("提示        : 能读到包元数据但无法导入，运行 python bootstrap.py 修复。")
    print("系统浏览器  : %s" % (report["browser_channel"] or "未检测到 Chrome/Edge"))
    print("离线 wheel  : %d 个" % len(report["offline_wheels"]))
    if not report["browser_channel"]:
        print("提示        : 请安装 Chrome 或 Edge。本工具不会下载 Playwright 自带 Chromium（150MB+）。")


def verify():
    try:
        return subprocess.run(
            [sys.executable, "-c", "from playwright.sync_api import sync_playwright; import pyee, greenlet"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
        ).returncode == 0
    except Exception:
        return False


def run(cmd, timeout):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired:
        return None


def tail_of(result):
    if result is None:
        return "超时"
    lines = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()
    errors = [line for line in lines if line.lstrip().startswith("ERROR:")]
    return (errors or lines or ["pip 返回非零"])[-1]


def install_offline():
    if not any(WHEELS.glob("*.whl")):
        return False, "wheels/ 中没有 whl"
    # Let pip resolve transitive dependencies from the local wheel set instead of
    # hard-coding file names; a wheel for another platform is then simply ignored.
    cmd = [sys.executable, "-m", "pip", "--isolated", "install", "--disable-pip-version-check",
           "--no-index", "--find-links", str(WHEELS), "--only-binary=:all:",
           "-r", str(REQUIREMENTS)]
    result = run(cmd, 180)
    if result is None or result.returncode != 0:
        return False, tail_of(result)
    if not verify():
        return False, "whl 与当前 Python/平台不匹配，或缺少传递依赖"
    return True, "已用离线 wheel 安装（未访问网络）"


def install_online():
    for mirror in MIRRORS:
        cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
               "--timeout", "8", "--retries", "0", "-i", mirror, "-r", str(REQUIREMENTS)]
        print("尝试镜像: " + mirror)
        result = run(cmd, 75)
        if result is not None and result.returncode == 0 and verify():
            return True, "已从 " + mirror + " 安装"
        print("  失败: " + tail_of(result))
    return False, "所有镜像均失败"


def current_tags():
    system = platform.system()
    machine = platform.machine().lower()
    py = "%d%d" % sys.version_info[:2]
    if system == "Windows":
        plat = "win_amd64" if machine in ("amd64", "x86_64") else "win32"
    elif system == "Darwin":
        plat = "arm64" if machine == "arm64" else "x86_64"
    else:
        plat = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    return system, py, plat


def plat_ok(name, system, plat):
    if system == "Windows":
        return plat in name
    if system == "Darwin":
        return "macosx" in name and ("universal2" in name or plat in name)
    return "manylinux" in name and plat in name


def simple_links(base, pkg):
    url = base.rstrip("/") + "/" + pkg + "/"
    data = urllib.request.urlopen(url, timeout=15).read().decode("utf-8", "ignore")
    return [urllib.parse.urljoin(url, h) for h in re.findall(r'href="([^"]+)"', data)]


def latest(urls):
    def key(url):
        match = re.search(r"-([0-9][0-9.]*)-", url)
        return tuple(int(x) for x in match.group(1).split(".")) if match else (0,)
    return sorted(urls, key=key)[-1]


def locked_playwright_version():
    """The pinned version in requirements.txt; the direct fallback must honour it."""
    try:
        text = REQUIREMENTS.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^\s*playwright\s*==\s*([0-9][0-9A-Za-z.+-]*)\s*$", text, re.M)
    return match.group(1) if match else None


def validate_wheel_set():
    """Never claim a wheel set is publishable until pip can install it offline."""
    with tempfile.TemporaryDirectory(prefix="vkn_wheel_check_") as target:
        cmd = [sys.executable, "-m", "pip", "--isolated", "install", "--disable-pip-version-check",
               "--no-index", "--find-links", str(WHEELS), "--only-binary=:all:",
               "--target", target, "-r", str(REQUIREMENTS)]
        result = run(cmd, 180)
    if result is None or result.returncode != 0:
        return False, tail_of(result)
    return True, "已用 pip 在隔离目录离线安装验证通过（版本与传递依赖均匹配）"


def download_wheels_direct():
    """Last resort when pip cannot reach an index: read a mirror's simple page directly.

    Unlike pip this path cannot resolve dependencies. It therefore downloads the
    *pinned* Playwright version (never "latest") and the whole result must pass
    validate_wheel_set() before the script calls it publishable.
    """
    system, py, plat = current_tags()
    locked = locked_playwright_version()
    if not locked:
        print("  无法从 requirements.txt 读取锁定的 playwright 版本")
        return False
    base = None
    for mirror in MIRRORS:
        try:
            if simple_links(mirror, "playwright"):
                base = mirror
                break
        except Exception:
            continue
    if not base:
        print("  所有镜像的 simple 页面都不可达")
        return False
    print("  直连页面: " + base)
    jobs = [
        ("playwright", "playwright", r"playwright-" + re.escape(locked) + r"-py3-none-[^/]*\.whl", True),
        ("pyee", "pyee", r"pyee-[0-9][^-]*-py3-none-any\.whl", False),
        ("greenlet", "greenlet", r"greenlet-[0-9][^-]*-cp" + py + r"-cp" + py + r"-[^/]*\.whl", True),
        ("typing_extensions", "typing-extensions", r"typing_extensions-[0-9][^-]*-py3-none-any\.whl", False),
    ]
    WHEELS.mkdir(parents=True, exist_ok=True)
    got = []
    for pkg, slug, pattern, check_plat in jobs:
        try:
            candidates = [u for u in simple_links(base, slug)
                          if re.search(pattern, u) and (not check_plat or plat_ok(u, system, plat))]
            if not candidates:
                print("  跳过 %s：镜像上找不到匹配锁定版本/当前平台的 wheel" % pkg)
                continue
            url = latest(candidates).split("#")[0]
            target = WHEELS / url.rsplit("/", 1)[1]
            if not target.exists():
                with urllib.request.urlopen(url, timeout=120) as stream, open(target, "wb") as out:
                    out.write(stream.read())
            print("  已下载 " + target.name)
            got.append(pkg)
        except Exception as exc:
            print("  跳过 %s：%s" % (pkg, type(exc).__name__))
    missing = {job[0] for job in jobs} - set(got)
    if missing:
        print("  离线包不完整，缺少：" + ", ".join(sorted(missing)))
        return False
    return True


def download_wheels():
    WHEELS.mkdir(parents=True, exist_ok=True)
    for mirror in MIRRORS:
        cmd = [sys.executable, "-m", "pip", "download", "--only-binary=:all:",
               "--dest", str(WHEELS), "--timeout", "8", "--retries", "0",
               "-i", mirror, "-r", str(REQUIREMENTS)]
        print("下载依赖到 wheels/，镜像: " + mirror)
        result = run(cmd, 120)
        if result is not None and result.returncode == 0:
            break
        print("  失败: " + tail_of(result))
    else:
        print("pip 无法访问索引，改用直连镜像页面下载（严格按 requirements.txt 锁定版本）…")
        if not download_wheels_direct():
            print("离线包生成失败：未取得完整且版本匹配的 wheel 集合。")
            print("请在能联网的机器上手工下载匹配版本的 whl 放入 wheels/ 后重试；这批文件不要发布。")
            return 2
    print("wheels/ 内容:")
    for path in sorted(WHEELS.glob("*.whl")):
        print("  " + path.name)
    ok, message = validate_wheel_set()
    if not ok:
        print("离线包校验失败：" + message)
        print("这批 wheel 不能发布。请清空 wheels/ 后重新生成，或手工补齐匹配当前平台的依赖。")
        return 2
    print(message)
    print("把这批文件打包发布即可；使用者运行 python bootstrap.py 会优先离线安装。")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Fast, browser-download-free setup")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--doctor", action="store_true", help="only inspect, install nothing")
    group.add_argument("--download-wheels", action="store_true", help="maintainer: build an offline wheel set")
    args = parser.parse_args()

    if sys.version_info < (3, 10):
        print("需要 Python 3.10 或更高版本。随包的 Windows x64 离线 wheel 需要 CPython 3.13。")
        return 2

    report = inspect()
    show(report)

    if args.download_wheels:
        return download_wheels()
    if args.doctor:
        print("未安装任何东西。" + ("依赖已就绪，可直接使用。" if report["deps_ready"] else "下一步：python bootstrap.py"))
        print("Playwright 是必需依赖，本项目没有跳过安装的降级路径。")
        print("已有字幕或有效缓存可直接用于写笔记；专用浏览器登录和在线取字幕才需要它。")
        return 0

    if report["deps_ready"]:
        print("依赖已就绪。验证：python scripts/browser_subtitles.py doctor")
        return 0

    ok, message = install_offline()
    if not ok:
        print("离线安装未采用：" + message)
        ok, message = install_online()
    if ok:
        print("完成：" + message)
        print("不要运行 playwright install chromium；系统浏览器会被直接复用。")
        return 0

    print("安装失败：" + message)
    print("Playwright 是必需依赖，本项目没有跳过安装的降级路径。")
    print("诊断：python bootstrap.py --doctor")
    print("离线方案：让维护者运行 python bootstrap.py --download-wheels 并把 wheels/ 发给你。")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
