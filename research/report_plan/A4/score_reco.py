"""2번 — 추천 기록(reco_v1) 형식 검사와 채점기(참조 구현).

보고서 1건 = JSON 한 줄(JSONL). 채점은 common.Engine(무작위 기준선과 같은 비용·같은 체결 규칙)으로 한다.
- 진입 조건이 실제로 충족됐는지(체결 여부·시각·가격), 손절·목표 중 먼저 닿은 것(1분봉, 2023-10 전은 5분봉),
  R(비용·펀딩 포함), MFE/MAE(R), 같은 봉 모호 여부.
- '관망'은 같은 시각에 표준 탐침(R2 규칙: 시장가, 손절 1.5×ATR4h, 목표 2R, 72h)을 롱·숏 둘 다 넣어 본 결과로
  '휩쏘(둘 다 손절) = 피한 손실', '한쪽 목표 도달 = 놓친 기회'를 센다. 관망에 조건부 계획이 붙어 있으면 그것도 따로 채점.
- 진입 종류(entry.kind)
  market        : 발행 시각 + 지연(latency_min, 기본 5분) 뒤 첫 봉 시가
  limit         : entry.price 지정가(관통 체결, 메이커)
  zone          : [lo, hi] 구간 — 기본은 구간 가운데 지정가(fill='mid'); 'near'(가까운 끝)·'far'(먼 끝)로 민감도
  close_confirm : 구간에 닿은 뒤 confirm_tf 봉이 confirm_level 위(롱)/아래(숏)에서 마감하면, 마감 + 지연 뒤 시장가
  breakout      : confirm_tf 봉이 level 위(롱)/아래(숏)에서 마감하면 시장가
  invalidate    : 체결 전 confirm_tf 종가가 이 값 아래(롱)/위(숏)면 취소
실행: /home/user/1111/.venv/bin/python score_reco.py   (예시 기록 out/reco_demo.jsonl 을 만들어 채점 → out/reco_demo_scored.csv)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import numpy as np
import pandas as pd

import common as C

SCHEMA = "reco_v1"

# (이름, 형식, 필수, 설명)
FIELDS = [
    ("schema", "str", True, "'reco_v1'"),
    ("report_id", "str", True, "보고서 고유 번호(예: 2026-11-07T10:00+09:00#1)"),
    ("issued_at_utc", "iso", True, "텔레그램으로 보낸 시각(UTC). 채점은 이 시각 뒤 데이터만 쓴다"),
    ("data_cutoff_utc", "iso", True, "계산에 쓴 마지막 '마감된' 봉의 마감 시각"),
    ("price_at_issue", "num", True, "발행 시각 직전 가격(마지막 1분봉 종가)"),
    ("action", "enum", True, "long | short | watch"),
    ("entry", "obj", False, "action이 long/short일 때 필수: {kind, price | lo,hi | level, confirm_tf, confirm_level, fill, latency_min}"),
    ("valid_until_utc", "iso", False, "진입 조건 유효 시각(지나면 미체결 만료). market이면 생략"),
    ("stop", "num", False, "손절 가격(long/short 필수)"),
    ("targets", "list", False, "[{price, share}] share 합 = 1. 1개면 share 생략 가능"),
    ("max_hold_h", "num", False, "체결 뒤 최대 보유 시간(시간). 없으면 72"),
    ("invalidate", "obj", False, "{tf, close_below | close_above} — 체결 전 이 종가가 나오면 취소"),
    ("leverage_hint", "num", False, "제안 레버리지(채점에는 안 씀, 사이징 검사용)"),
    ("risk_pct_hint", "num", False, "제안 1회 위험(계좌 %)"),
    ("watch_plan", "obj", False, "관망일 때의 조건부 계획(같은 형식의 entry/stop/targets/valid_until_utc)"),
    ("rules_cited", "list", True, "근거 규칙 번호 목록(예: CP-12-6, WY-07-1, ENG-TR-2)"),
    ("views", "obj", True, "{cp: long|short|watch, wy: ..., claude: ...} 세 관점 각각의 결론"),
    ("confidence", "num", False, "0~1 주관 확신도(보정 검사용)"),
    ("engine_version", "str", True, "계산 엔진 버전(git 커밋 해시)"),
    ("engine_decision", "obj", True, "엔진만의 판단 {action, entry, stop, targets} — Claude 층 가치 비교용"),
    ("model_id", "str", True, "예: claude-opus-5-5 (엔진만이면 'none')"),
    ("prompt_version", "str", True, "지시문 파일 이름 + 해시"),
    ("playbook_version", "str", True, "기준서 버전(예: CP v0.2 + WY v0.2) + 해시"),
    ("input_hash", "str", True, "모델에 넣은 사실 JSON·그림의 sha256"),
    ("output_hash", "str", True, "모델 원응답의 sha256(원문은 따로 저장)"),
    ("tokens", "obj", False, "{input, cache_read, cache_write, output}"),
    ("cost_usd", "num", False, "호출 비용 추정"),
    ("latency_s", "num", False, "분석에 걸린 시간"),
    ("status", "enum", True, "ok | refusal | truncated | schema_invalid | timeout | error (실패도 기록)"),
]
REQ_TRADE = ("entry", "stop", "targets")
PROBE = dict(atr_tf="4h", k=1.5, tr=2.0, hold=72)   # 관망 탐침 = 무작위 기준선 R2


def _iso_ns(s: str) -> int:
    return C.utc(s.replace("Z", "")) if isinstance(s, str) else int(s)


def validate(rec: dict) -> list[str]:
    errs = []
    for name, typ, req, _ in FIELDS:
        if req and name not in rec:
            errs.append(f"필수 항목 없음: {name}")
    if rec.get("schema") != SCHEMA:
        errs.append("schema가 reco_v1이 아님")
    act = rec.get("action")
    if act not in ("long", "short", "watch"):
        errs.append(f"action 값 이상: {act}")
    if act in ("long", "short"):
        for k in REQ_TRADE:
            if k not in rec:
                errs.append(f"{act}인데 {k} 없음")
        if "stop" in rec and "price_at_issue" in rec:
            side = 1 if act == "long" else -1
            if side * (rec["price_at_issue"] - rec["stop"]) <= 0:
                errs.append("손절이 진입 방향 반대편이 아님(롱인데 손절이 위 등)")
        tg = rec.get("targets") or []
        if tg and abs(sum(t.get("share", 1.0 / len(tg)) for t in tg) - 1) > 1e-6:
            errs.append("targets share 합이 1이 아님")
        e = rec.get("entry", {})
        if e.get("kind") not in ("market", "limit", "zone", "close_confirm", "breakout"):
            errs.append(f"entry.kind 이상: {e.get('kind')}")
        if e.get("kind") != "market" and "valid_until_utc" not in rec:
            errs.append("market이 아닌데 valid_until_utc 없음")
    try:
        if _iso_ns(rec["data_cutoff_utc"]) > _iso_ns(rec["issued_at_utc"]):
            errs.append("data_cutoff가 발행 시각보다 늦음(미래 정보 의심)")
    except Exception:  # noqa: BLE001
        errs.append("시각 형식 오류")
    return errs


class Scorer:
    def __init__(self):
        self.eng = C.Engine()
        self.tf = {tf: C.load_tf(tf) for tf in ("1h", "4h", "1d")}
        self.atr4 = C.atr(self.tf["4h"], 14)

    # --- 확정 봉 종가 조건 찾기 ---
    def first_close(self, tf: str, t0: int, t1: int, cond) -> int | None:
        b = self.tf[tf]
        ct = b.close_t
        a = int(np.searchsorted(ct, t0, side="right"))
        z = int(np.searchsorted(ct, t1, side="right"))
        if z <= a:
            return None
        ok = cond(b.c[a:z], b.l[a:z], b.h[a:z])
        if not ok.any():
            return None
        return int(ct[a + int(np.argmax(ok))])

    def _one_target(self, side, start, plan, tgt_price, **kw) -> C.TradeOut:
        return self.eng.run(side, start, stop=plan["stop"], target=tgt_price, max_hold_ns=int(plan.get("max_hold_h", 72) * C.NS_HOUR), **kw)

    def score_plan(self, side: int, issued: int, plan: dict) -> dict:
        """long/short 계획 1건 → 체결·결과. 목표가 여러 개면 share로 가중 평균(손절은 고정, 본전 이동 없음)."""
        e = plan["entry"]
        lat = int(e.get("latency_min", 5)) * C.NS_MIN
        valid = _iso_ns(plan["valid_until_utc"]) if "valid_until_utc" in plan else issued + lat + C.NS_MIN
        tg = plan["targets"]
        shares = [t.get("share", 1.0 / len(tg)) for t in tg]
        kind = e["kind"]
        # 무효화(체결 전 취소) 시각
        cancel_t = None
        inv = plan.get("invalidate")
        if inv:
            if "close_below" in inv:
                cancel_t = self.first_close(inv["tf"], issued, valid, lambda c, l, h, x=inv["close_below"]: c < x)
            if "close_above" in inv:
                ct2 = self.first_close(inv["tf"], issued, valid, lambda c, l, h, x=inv["close_above"]: c > x)
                cancel_t = ct2 if cancel_t is None else min(cancel_t, ct2 or cancel_t)
        eff_valid = min(valid, cancel_t) if cancel_t else valid
        outs = []
        trig_t = None
        if kind == "market":
            for t in tg:
                outs.append(self._one_target(side, issued + lat, plan, t["price"]))
        elif kind in ("limit", "zone"):
            if kind == "limit":
                px = e["price"]
            else:
                lo, hi = e["lo"], e["hi"]
                fill = e.get("fill", "mid")
                near, far = (hi, lo) if side > 0 else (lo, hi)
                px = {"mid": (lo + hi) / 2, "near": near, "far": far}[fill]
            for t in tg:
                outs.append(self._one_target(side, issued + lat, plan, t["price"], entry="limit", limit_px=px, valid_until=eff_valid))
        elif kind in ("close_confirm", "breakout"):
            tf = e.get("confirm_tf", "4h")
            if kind == "close_confirm":
                lo, hi = e["lo"], e["hi"]
                lvl = e.get("confirm_level", hi if side > 0 else lo)
                touch = self.first_close("1h", issued, eff_valid,
                                         (lambda c, l, h: l <= hi) if side > 0 else (lambda c, l, h: h >= lo))
                if touch is not None:
                    t0 = touch - C.NS_HOUR
                    trig_t = self.first_close(tf, t0, eff_valid, (lambda c, l, h: c >= lvl) if side > 0 else (lambda c, l, h: c <= lvl))
            else:
                lvl = e["level"]
                trig_t = self.first_close(tf, issued, eff_valid, (lambda c, l, h: c > lvl) if side > 0 else (lambda c, l, h: c < lvl))
            if trig_t is not None:
                for t in tg:
                    outs.append(self._one_target(side, trig_t + lat, plan, t["price"]))
        res = dict(triggered=False, cancelled=bool(cancel_t and (not outs or all(o.status != "filled" for o in outs))))
        filled = [o for o in outs if o.status == "filled"]
        if not filled or len(filled) != len(outs):
            res["outcome"] = "cancelled" if res["cancelled"] else ("nodata" if any(o.status == "nodata" for o in outs) else "expired")
            return res
        f0 = filled[0]
        res.update(triggered=True, fill_t=f0.entry_t, fill_px=f0.entry_px, time_to_fill_h=(f0.entry_t - issued) / C.NS_HOUR,
                   outcome="+".join(sorted({o.exit_kind for o in filled})),
                   exit_t=max(o.exit_t for o in filled),
                   r=float(sum(s * o.r for s, o in zip(shares, filled))),
                   r_gross=float(sum(s * o.r_gross for s, o in zip(shares, filled))),
                   cost_r=float(sum(s * o.cost_r for s, o in zip(shares, filled))),
                   mfe_r=float(max(o.mfe_r for o in filled)), mae_r=float(max(o.mae_r for o in filled)),
                   ambiguous=any(o.ambiguous for o in filled), res_min=f0.res_min,
                   hold_h=(max(o.exit_t for o in filled) - f0.entry_t) / C.NS_HOUR)
        return res

    def probe(self, issued: int) -> dict:
        """관망 탐침: 같은 시각 R2 규칙 롱·숏."""
        ct = self.tf["4h"].close_t
        i = int(np.searchsorted(ct, issued, side="right")) - 1
        dist = PROBE["k"] * self.atr4[i]
        out = {}
        for side, nm in ((1, "long"), (-1, "short")):
            o = self.eng.run(side, issued + 5 * C.NS_MIN, stop_dist=dist, target_r=PROBE["tr"], max_hold_ns=PROBE["hold"] * C.NS_HOUR)
            out[f"probe_{nm}_r"] = o.r if o.status == "filled" else float("nan")
            out[f"probe_{nm}_kind"] = o.exit_kind
        kl, ks = out["probe_long_kind"], out["probe_short_kind"]
        out["watch_label"] = ("whipsaw(피한 손실)" if kl == "stop" and ks == "stop" else
                              "missed_up(놓친 상승)" if kl == "target" else
                              "missed_down(놓친 하락)" if ks == "target" else
                              "quiet(조용)" if kl == "time" and ks == "time" else "mixed")
        return out

    def score(self, rec: dict) -> dict:
        errs = validate(rec)
        issued = _iso_ns(rec["issued_at_utc"])
        row = dict(report_id=rec.get("report_id"), action=rec.get("action"), issued_kst=C.iso_kst(issued),
                   valid=not errs, errors="; ".join(errs), model_id=rec.get("model_id"),
                   prompt_version=rec.get("prompt_version"))
        if errs:
            return row
        if rec["action"] in ("long", "short"):
            side = 1 if rec["action"] == "long" else -1
            row.update(self.score_plan(side, issued, rec))
            # 진입 선택의 값: 같은 손절·목표로 '바로 시장가'였다면?
            alt = dict(rec, entry={"kind": "market"})
            alt.pop("valid_until_utc", None)
            a = self.score_plan(side, issued, alt)
            row["r_if_market_now"] = a.get("r", float("nan"))
        else:
            row.update(self.probe(issued))
            if rec.get("watch_plan"):
                wp = rec["watch_plan"]
                side = 1 if wp.get("side", "long") == "long" else -1
                sp = self.score_plan(side, issued, wp)
                row.update({f"plan_{k}": v for k, v in sp.items()})
        # 엔진만의 판단도 같은 방식으로 채점(A/B 비교용)
        ed = rec.get("engine_decision") or {}
        if ed.get("action") in ("long", "short"):
            side = 1 if ed["action"] == "long" else -1
            se = self.score_plan(side, issued, ed)
            row["engine_r"] = se.get("r", 0.0 if not se.get("triggered") else float("nan"))
            row["engine_triggered"] = se.get("triggered", False)
        else:
            row["engine_r"] = 0.0
            row["engine_triggered"] = False
        row["final_r_per_report"] = row.get("r", 0.0) if row.get("triggered") else 0.0
        return row


def kpis(df: pd.DataFrame) -> dict:
    """버전별 핵심 지표."""
    out = {}
    tr = df[df["action"].isin(["long", "short"])]
    trig = tr[tr["triggered"] == True]  # noqa: E712
    out["reports"] = int(len(df))
    out["trade_reports"] = int(len(tr))
    out["trigger_rate"] = float(len(trig) / len(tr)) if len(tr) else float("nan")
    out["R_triggered"] = C.r_summary(trig["r"].to_numpy()) if len(trig) else {}
    out["mean_R_per_report"] = float(df["final_r_per_report"].mean())
    out["engine_mean_R_per_report"] = float(df["engine_r"].mean())
    out["delta_llm_minus_engine"] = float((df["final_r_per_report"] - df["engine_r"]).mean())
    w = df[df["action"] == "watch"]
    if len(w):
        out["watch_labels"] = w["watch_label"].value_counts(normalize=True).to_dict()
    return out


def demo_records() -> list[dict]:
    """예시(가짜) 기록 3건 — 실제 추천이 아니다. 데이터의 그 시각 값으로 계획을 만든다."""
    b4 = C.load_tf("4h")
    a4 = C.atr(b4, 14)
    b1 = C.load_tf("1h")
    recs = []
    base = dict(schema=SCHEMA, rules_cited=["CP-10-2", "WY-07-1"], views=dict(cp="long", wy="watch", claude="long"),
                engine_version="demo", model_id="claude-opus-5-5", prompt_version="demo_v0", playbook_version="CP0.2+WY0.2",
                status="ok", confidence=0.55)
    for k, (when, act) in enumerate((("2026-08-12 01:00", "long"), ("2026-09-03 07:00", "short"), ("2026-09-15 00:00", "watch"))):
        t = C.utc(when)
        i1 = int(np.searchsorted(b1.close_t, t, side="right")) - 1
        i4 = int(np.searchsorted(b4.close_t, t, side="right")) - 1
        px = float(b1.c[i1])
        a = float(a4[i4])
        rec = dict(base, report_id=f"demo-{k}", issued_at_utc=pd.Timestamp(t + 2 * C.NS_MIN, unit="ns").isoformat(),
                   data_cutoff_utc=pd.Timestamp(int(b1.close_t[i1]), unit="ns").isoformat(), price_at_issue=px, action=act,
                   input_hash=hashlib.sha256(f"in{k}".encode()).hexdigest()[:16], output_hash=hashlib.sha256(f"out{k}".encode()).hexdigest()[:16])
        if act in ("long", "short"):
            s = 1 if act == "long" else -1
            lo, hi = sorted((px - s * 0.3 * a, px - s * 0.8 * a))
            stop = (lo - 1.0 * a) if s > 0 else (hi + 1.0 * a)
            mid = (lo + hi) / 2
            rec.update(entry=dict(kind="zone", lo=round(lo, 1), hi=round(hi, 1), fill="mid"),
                       valid_until_utc=pd.Timestamp(t + 12 * C.NS_HOUR, unit="ns").isoformat(), stop=round(stop, 1),
                       targets=[dict(price=round(mid + s * 2.0 * abs(mid - stop), 1), share=0.5),
                                dict(price=round(mid + s * 3.0 * abs(mid - stop), 1), share=0.5)],
                       max_hold_h=72, invalidate=dict(tf="4h", **({"close_below": round(stop, 1)} if s > 0 else {"close_above": round(stop, 1)})))
            rec["engine_decision"] = dict(action=act, entry=dict(kind="market"), stop=rec["stop"], targets=[dict(price=rec["targets"][0]["price"])])
        else:
            rec["watch_plan"] = dict(side="long", entry=dict(kind="close_confirm", lo=round(px - 1.0 * a, 1), hi=round(px - 0.4 * a, 1), confirm_tf="4h"),
                                     valid_until_utc=pd.Timestamp(t + 24 * C.NS_HOUR, unit="ns").isoformat(),
                                     stop=round(px - 2.0 * a, 1), targets=[dict(price=round(px + 1.6 * a, 1))], max_hold_h=72)
            rec["engine_decision"] = dict(action="long", entry=dict(kind="market"), stop=round(px - 1.5 * a, 1), targets=[dict(price=round(px + 3.0 * a, 1))])
        recs.append(rec)
    return recs


def main():
    recs = demo_records()
    with open(C.OUT / "reco_demo.jsonl", "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    sc = Scorer()
    rows = [sc.score(r) for r in recs]
    df = pd.DataFrame(rows)
    df.to_csv(C.OUT / "reco_demo_scored.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 50)
    print(df.T)
    print(json.dumps(kpis(df), ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
