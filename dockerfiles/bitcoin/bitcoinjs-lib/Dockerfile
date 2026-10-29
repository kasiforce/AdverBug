# Reproducible benchmark image for bitcoinjs/bitcoinjs-lib.
FROM node:24-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

RUN git clone https://github.com/bitcoinjs/bitcoinjs-lib.git . \
    && git checkout --detach ab9fad5978bc1f4fb6542d1cde903d4427c3344e \
    && git remote remove origin

RUN npm ci --ignore-scripts --no-audit --no-fund \
    && npm run build

RUN mkdir -p /testbed/.adverbug_jest_runtime \
    && printf '%s\n' '{"name":"adverbug-jest-runtime","private":true}' > /testbed/.adverbug_jest_runtime/package.json \
    && cd /testbed/.adverbug_jest_runtime \
    && npm install --no-save --ignore-scripts --no-audit --no-fund jest@30.0.5

RUN ln -sf /testbed/.adverbug_jest_runtime/node_modules/.bin/jest /usr/local/bin/jest

ENV NODE_OPTIONS=--experimental-vm-modules \
    PATH=/testbed/node_modules/.bin:/testbed/.adverbug_jest_runtime/node_modules/.bin:${PATH}

CMD ["bash"]
