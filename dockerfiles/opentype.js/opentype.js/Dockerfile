# Reproducible benchmark image for opentypejs/opentype.js.
FROM node:24-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    NODE_OPTIONS=--experimental-vm-modules

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

RUN git clone https://github.com/opentypejs/opentype.js.git /testbed \
    && cd /testbed \
    && git checkout --detach 5d65b6dcfab5115f90d375f8ba6b7942fdaa0138 \
    && git remote remove origin

RUN npm ci --ignore-scripts --no-audit --no-fund

RUN mkdir -p /testbed/.adverbug_jest_runtime \
    && printf '%s\n' '{"name":"adverbug-jest-runtime","private":true}' > /testbed/.adverbug_jest_runtime/package.json \
    && cd /testbed/.adverbug_jest_runtime \
    && npm install --no-save --ignore-scripts --no-audit --no-fund jest@30.0.5

ENV PATH=/testbed/node_modules/.bin:/testbed/.adverbug_jest_runtime/node_modules/.bin:${PATH}

WORKDIR /testbed
CMD ["bash"]
