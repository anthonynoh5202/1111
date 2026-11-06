import json, sys, urllib.request, re
req = open(sys.argv[1]).read()
blocks = re.findall(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)((?:\s*\\\s*--hash=sha256:[0-9a-f]{64})+)", req, re.M)
for name, ver, hs in blocks:
    have = set(re.findall(r"sha256:([0-9a-f]{64})", hs))
    d = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json", timeout=30))
    mac = [f for f in d["urls"] if "macosx" in f["filename"] and ("arm64" in f["filename"] or "universal2" in f["filename"])]
    pure = [f for f in d["urls"] if f["filename"].endswith("none-any.whl")]
    mac_cov = [f["filename"] for f in mac if f["digests"]["sha256"] in have]
    pure_cov = [f["filename"] for f in pure if f["digests"]["sha256"] in have]
    py = lambda fn: (re.search(r"-(cp3\d+|py3)-", fn) or [None, "?"])[1]
    status = "OK(pure)" if pure_cov else ("OK(mac arm64: " + ",".join(sorted({py(x) for x in mac_cov})) + ")" if mac_cov else "MISSING mac arm64")
    print(f"{name}=={ver}: hashes={len(have)} -> {status}")
