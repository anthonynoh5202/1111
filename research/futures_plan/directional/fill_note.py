"""Fill {{T_*}} placeholders in note_template.md with sections of out/tables.md and write the research note."""
import os
import re
from common import OUT, BASE

DEST = '/home/user/1111/research_notes/비트코인 선물 수익 전략과 실행 계획/quant_directional.md'
sections = {}
cur = None
for line in open(f'{OUT}/tables.md', encoding='utf-8').read().splitlines():
    if line.startswith('## '):
        cur = line[3:].split()[0]
        sections[cur] = []
        continue
    if cur is not None:
        sections[cur].append(line)
sections = {k: '\n'.join(v).strip() for k, v in sections.items()}
tpl = open(os.path.join(BASE, 'note_template.md'), encoding='utf-8').read()
missing = []


def rep(m):
    key = m.group(1)
    if key not in sections:
        missing.append(key)
        return m.group(0)
    return sections[key]


out = re.sub(r'\{\{(T_[A-Z0-9_]+)\}\}', rep, tpl)
assert not missing, missing
assert '{{' not in out
os.makedirs(os.path.dirname(DEST), exist_ok=True)
open(DEST, 'w', encoding='utf-8').write(out)
print('written', DEST, len(out), 'chars', out.count('\n'), 'lines')
