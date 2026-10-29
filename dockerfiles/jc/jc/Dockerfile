FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

RUN git clone --filter=blob:none https://github.com/kellyjonbrazil/jc.git . \
    && git checkout --detach 73fa7d5572dd730076723bd6280786bb9101d32f \
    && git remote remove origin

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -e . pytest pytest-json-report

CMD ["python", "-m", "pytest", "--no-header", "-rA", "--tb=no", "-p", "no:cacheprovider", "tests"]
