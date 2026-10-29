ARG BASE_IMAGE
FROM ${BASE_IMAGE}

USER root
RUN python -m pip install \
    pytest \
    pytest-json-report \
    pytest-timeout \
    coverage \
    pytest-asyncio \
    pytest-mock
