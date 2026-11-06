import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
# split by "def " at 4-space indent inside class
parts = re.split(r"\n    def ", src)
want = sys.argv[2:]
for p in parts[1:]:
    name = p.split("(", 1)[0]
    if want and not any(w in name for w in want):
        continue
    m = re.search(r'"""(.*?)"""', p, re.S)
    doc = m.group(1) if m else ""
    # endpoint path
    path = re.search(r'path\s*=\s*f?"([^"]+)"', p)
    print("=" * 100)
    print(name, "->", path.group(1) if path else "?")
    # strip Args section to keep it short
    doc = doc.split("Args:")[0]
    print("\n".join(l.strip() for l in doc.strip().splitlines() if l.strip())[:3000])
