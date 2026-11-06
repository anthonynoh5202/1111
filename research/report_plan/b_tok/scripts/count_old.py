import sys, json
from tokenizers import Tokenizer
tok = Tokenizer.from_file(sys.argv[1])
for p in sys.argv[2:]:
    s = open(p, encoding="utf-8").read()
    ids = tok.encode(s).ids
    hangul = sum(1 for c in s if '가' <= c <= '힣')
    # 한글만 / ASCII만 분리 측정
    only_h = "".join(c if ('가' <= c <= '힣' or c == ' ') else ' ' for c in s)
    only_a = "".join(c if ord(c) < 128 else ' ' for c in s)
    nh = len(tok.encode(only_h).ids); na = len(tok.encode(only_a).ids)
    print(f"{p.split('/')[-1]}: chars={len(s)} hangul={hangul} old_tokens={len(ids)} tok/char={len(ids)/len(s):.3f} | hangul-only text tokens={nh} ({nh/max(hangul,1):.2f}/hangul) | ascii-only tokens={na}")
