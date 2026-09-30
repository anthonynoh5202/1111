"""TESTNET 주문 프로세스(B) — 주문 게이트웨이·방화벽·대조·가짜 거래소. 설계: bot/orders/DESIGN.md.

프로세스 A(bot.main: 분석·텔레그램)는 이 패키지에서 ``queue``(enqueue·cancel_queued·request_exit)와
``types``만 쓴다. 거래 키를 읽는 코드(binance_client, worker)는 프로세스 B에서만 import한다.
"""
