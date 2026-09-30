"""BTC 추세추종 모의 운영(PAPER) 봇 — bot/DESIGN.md 참고.

범위: 신호 계산(backtest.trend 재사용) → 텔레그램 카드 → 사람 2단계 승인 → 모의 체결·손절·청산 → 기록.
거래소 API 키·실주문 코드는 이 패키지에 없다(다음 단계). 실제 돈이 움직이는 코드는 만들지 않는다.
"""

__all__ = ["BOT_VERSION"]

BOT_VERSION = "0.1.0-paper"
