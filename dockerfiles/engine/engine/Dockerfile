# Reproducible benchmark image for playcanvas/engine.
FROM node:24-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    NODE_OPTIONS=--experimental-vm-modules

# canvas may use a native fallback on architectures without a prebuilt binary.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential python3 pkg-config \
        libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

RUN git clone https://github.com/playcanvas/engine.git /testbed \
    && cd /testbed \
    && git checkout --detach 342ec1a04585928918d60fea1af900fbfec3cb7a \
    && git remote remove origin

RUN npm ci --no-audit --no-fund

# The project uses Mocha natively.  Keep an isolated Jest runner for the
# benchmark's generated tests without changing package.json or package-lock.
RUN mkdir -p /testbed/.adverbug_jest_runtime \
    && printf '%s\n' '{"name":"adverbug-jest-runtime","private":true}' > /testbed/.adverbug_jest_runtime/package.json \
    && cd /testbed/.adverbug_jest_runtime \
    && npm install --no-save --ignore-scripts --no-audit --no-fund jest@30.0.5

ENV PATH=/testbed/node_modules/.bin:/testbed/.adverbug_jest_runtime/node_modules/.bin:${PATH}

WORKDIR /testbed
CMD ["bash"]
