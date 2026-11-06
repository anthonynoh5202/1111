"""doc_template.md + out/tables.md(+ score_reco.FIELDS) → ../A4_validation.md"""
from __future__ import annotations

import re

import common as C
from score_reco import FIELDS

tpl = (C.HERE / "doc_template.md").read_text(encoding="utf-8")
tables = (C.OUT / "tables.md").read_text(encoding="utf-8")

blocks = {}
parts = re.split(r"(?m)^(?=#### T\d+\.)", tables)
for p in parts:
    m = re.match(r"#### (T\d+)\.", p)
    if m:
        blocks[m.group(1)] = p.strip()

fields = ["| 항목 | 형식 | 필수 | 설명 |", "|---|---|:---:|---|"]
for name, typ, req, desc in FIELDS:
    fields.append(f"| `{name}` | {typ} | {'○' if req else ''} | {desc.replace(chr(124), chr(47))} |")
blocks["FIELDS"] = "\n".join(fields)


def sub(m):
    k = m.group(1)
    if k not in blocks:
        raise KeyError(k)
    return blocks[k]


out = re.sub(r"\{\{(T\d+|FIELDS)\}\}", sub, tpl)
assert "{{" not in out
dst = C.HERE.parent / "A4_validation.md"
dst.write_text(out, encoding="utf-8")
print(dst, len(out), "chars", out.count("\n"), "lines")
