import json, sys, urllib.request, re, collections
pkgs = [l.split() for l in sys.stdin.read().strip().splitlines()]
for name, ver in pkgs:
    url = f"https://pypi.org/pypi/{name}/{ver}/json"
    try:
        d = json.load(urllib.request.urlopen(url, timeout=30))
    except Exception as e:
        print(name, ver, "ERR", e); continue
    files = d["urls"]
    plat = collections.Counter()
    mac_arm = []
    for f in files:
        fn = f["filename"]
        if fn.endswith(".tar.gz"): plat["sdist"] += 1; continue
        if "macosx" in fn and ("arm64" in fn or "universal2" in fn): plat["mac_arm64"] += 1; mac_arm.append(fn)
        elif "macosx" in fn: plat["mac_x86"] += 1
        elif "manylinux" in fn or "musllinux" in fn: plat["linux"] += 1
        elif "win" in fn: plat["win"] += 1
        elif fn.endswith("none-any.whl"): plat["pure"] += 1
        else: plat["other"] += 1
    pys = sorted({m.group(1) for f in files for m in [re.search(r"-(cp3\d+)-", f["filename"])] if m})
    print(f"{name}=={ver}: files={len(files)} {dict(plat)} py={pys[:2]}..{pys[-2:] if pys else ''} upload={files[0]['upload_time'][:10] if files else ''}")
