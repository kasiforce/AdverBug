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

RUN git clone --filter=blob:none https://github.com/plotly/plotly.py.git . \
    && git checkout --detach 38374acdce011d08a71cf92ade2abd4a1e4c7c92 \
    && git remote remove origin

# Install the package and the dependencies used by the checked-in tests.  The
# original image used Conda, an unavailable chromium-browser package, and an
# obsolete algoliasearch Conda pin; none of these are needed for unit tests.
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -e '.[dev_core,dev_codegen,express]' \
    && pip install pytest pytest-json-report pandas matplotlib

CMD ["python", "-m", "pytest", "--no-header", "-rA", "--tb=no", "-p", "no:cacheprovider", "test_init", "tests"]
