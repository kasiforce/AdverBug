# SQLGlot supports Python 3.9+; Python 3.10 is needed for its current mypyc
# development dependency.
FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates git build-essential libffi-dev libtiff-dev jq curl make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

RUN git clone https://github.com/tobymao/sqlglot.git . \
    && git checkout --detach caa920da583f57913311798aff2561821ea8ca01 \
    && git remote remove origin

RUN python -m pip install --upgrade pip setuptools wheel setuptools_scm \
    && pip install -e . \
    && pip install -e ".[dev]" \
    && pip install pytest

CMD ["make", "check"]
