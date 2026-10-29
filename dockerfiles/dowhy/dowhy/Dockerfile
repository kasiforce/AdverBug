# DoWhy supports Python 3.9+, while current dependency releases require newer
# interpreters. Python 3.11 gives a stable wheel-based environment.
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
       ca-certificates git build-essential graphviz libgraphviz-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

RUN git clone --filter=blob:none https://github.com/py-why/dowhy.git . \
    && git checkout --detach f34dd630d7e32dff71b47e29cfc0d3bb886c0000 \
    && git remote remove origin

RUN python -m pip install --upgrade pip setuptools wheel poetry-core cython \
    && pip install scipy numpy pandas statsmodels sympy scikit-learn networkx \
       matplotlib pydot pygraphviz sphinx seaborn cdt nbconvert nbsphinx IPython \
    && pip install -e . \
    && pip install pytest flaky

CMD ["pytest", "--no-header", "-rA", "--tb=no", "-p", "no:cacheprovider", "tests/"]
