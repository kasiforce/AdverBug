# This revision requires Python 3.12+.  A regular wheel installation avoids
# scikit-learn's editable loader rebuilding against a deleted temporary env.
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates git build-essential ninja-build \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install \
       'numpy>=2' 'scipy>=1.11.4' 'joblib>=1.4.0' 'narwhals>=2.0.1' \
       'threadpoolctl>=3.5.0' 'matplotlib>=3.8.0' 'scikit-image>=0.24.0' \
       'pandas>=2.1.3' 'seaborn>=0.13.0' 'plotly>=5.24.0' \
       'pytest>=7.1.2' 'meson-python>=0.17.1' 'cython>=3.1.2,<3.2.6'

WORKDIR /testbed

RUN git clone --filter=blob:none https://github.com/scikit-learn/scikit-learn.git . \
    && git checkout --detach d0e22aee7bbef7b310a2f08227c214ff6df9a526 \
    && git remote remove origin \
    && rm -rf build \
    && pip install . --no-build-isolation

# Import the installed wheel from outside the source checkout.
RUN cd /tmp && python -c 'import sklearn; print(sklearn.__version__)'

CMD ["bash", "-lc", "cd /tmp && pytest --no-header -rA --tb=no -p no:cacheprovider /testbed/sklearn"]
