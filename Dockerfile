# BTC 추세추종 모의 운영(PAPER) 봇 이미지 — bot/DESIGN.md §7.5, §11
# - 비루트 사용자(uid 10001), 인바운드 포트 없음(EXPOSE 없음), 비밀은 /run/secrets 파일로만.
# - 신호 코드 재사용을 위해 backtest/*.py(코드만)를 함께 넣는다(B-15). 결과·검증·테스트·데이터는 넣지 않는다.
# - 베이스 이미지는 digest로 고정한다(INFRA H17, PV-07). 태그만 쓰면 같은 태그가 다른 이미지로 바뀔 수 있다.
#   아래 digest = 2026-09-30에 레지스트리에서 확인한 python:3.11-slim 다중 아키텍처 인덱스.
#   올릴 때: docker buildx imagetools inspect python:3.11-slim  (Digest 줄) → 아래 값 교체 → 테스트 → 커밋.
FROM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

RUN useradd --uid 10001 --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin bot \
 && mkdir -p /app /data /config \
 && chown bot:bot /data

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r /app/requirements.txt   # PV-24: 해시 검증

# 코드: root 소유 읽기 전용(실행 사용자가 코드를 고칠 수 없게)
COPY bot/ /app/bot/
COPY backtest/*.py /app/backtest/
RUN rm -rf /app/bot/tests && find /app -name '__pycache__' -prune -exec rm -rf {} + \
 && chmod -R a-w /app

USER 10001:10001

# 설정은 /config/bot.toml(읽기 전용 마운트), DB는 /data(볼륨). 기본 명령은 paper 실행.
ENTRYPOINT ["python", "-m", "bot.main", "--config", "/config/bot.toml"]
CMD ["run"]
