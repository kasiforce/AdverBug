FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

RUN git clone https://github.com/Textualize/textual.git . \
    && git checkout --detach 5e5b7ef58b8c5572c13a3ff9027d756623661495 \
    && git remote remove origin

# Install the package directly with its PEP 517 backend.  Only the test tools
# are added explicitly; installing Poetry and its lockfile dependencies makes
# the image unnecessarily sensitive to an unrelated PyPI/Conda outage.
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -e . \
    && pip install pytest pytest-xdist pytest-asyncio pytest-cov pytest-textual-snapshot

CMD ["python", "-m", "pytest", "--no-header", "-rA", "--tb=short", "-p", "no:cacheprovider", "tests"]
