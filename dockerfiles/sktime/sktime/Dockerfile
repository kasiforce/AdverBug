FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

RUN git clone --filter=blob:none https://github.com/sktime/sktime.git . \
    && git checkout --detach e1a1fc34c56478f0280a8518165a5be56e8a8dee \
    && git remote remove origin

# Install the core, common optional estimators, and test tooling.  This avoids
# the repository's Conda setup while covering the modules represented in the
# selected benchmark functions.
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -e '.[all_extras,dev,tests]' \
    && pip install pytest-json-report

CMD ["python", "-m", "pytest", "--no-header", "-rA", "--tb=no", "-p", "no:cacheprovider", "sktime/tests"]
