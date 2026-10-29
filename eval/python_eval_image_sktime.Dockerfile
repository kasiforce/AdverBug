ARG BASE_IMAGE
FROM ${BASE_IMAGE}

USER root

# Match the optional deep-learning environment used while generating the
# sktime tests.  Install the CPU wheel explicitly so the evaluation image does
# not pull CUDA runtime packages.
RUN python -m pip install --no-cache-dir \
        numpy==1.26.4 \
    && python -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.2.2 \
    && python -m pip install --no-cache-dir \
        transformers==4.40.2 \
        torchdiffeq==0.2.5 \
        pytest \
        pytest-json-report \
        pytest-timeout \
        coverage \
        pytest-asyncio \
        pytest-mock
