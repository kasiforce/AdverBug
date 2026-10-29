# Darts requires Python 3.11 or newer.  Use the official Python image so the
# benchmark does not depend on Conda channel availability or ToS prompts.
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl git build-essential libffi-dev patch jq locales \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

RUN git clone --filter=blob:none https://github.com/unit8co/darts.git . \
    && git checkout --detach ebde4b0646f3ddd315ae13651c1bc956902995be \
    && git remote remove origin

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -e . \
    && pip install pytest pytest-json-report pre-commit typing_extensions ipython

CMD ["pytest", "--no-header", "-rA", "--tb=no", "-p", "no:cacheprovider"]
