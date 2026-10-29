# Reproducible benchmark image for imba/imba.
FROM node:24-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    NODE_OPTIONS=--experimental-vm-modules

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

# The checked-in generated JS uses extensionless ESM imports. Node's native
# resolver requires an exact file, so provide the compatibility link used by
# the standalone package's test tooling.
RUN git clone https://github.com/imba/imba.git /testbed \
    && cd /testbed \
    && git checkout --detach 549019012bf4d4bb083d326cfcf1f7531abef23a \
    && git remote remove origin \
    && ln -s common.js packages/imba-monarch/src/monarch/common

# npm workspaces perform the dependency linking; the old `lerna bootstrap`
# command is intentionally not used because it was removed from modern Lerna.
RUN npm ci --ignore-scripts --no-audit --no-fund

RUN mkdir -p /testbed/.adverbug_jest_runtime \
    && printf '%s\n' '{"name":"adverbug-jest-runtime","private":true}' > /testbed/.adverbug_jest_runtime/package.json \
    && cd /testbed/.adverbug_jest_runtime \
    && npm install --no-save --ignore-scripts --no-audit --no-fund jest@30.0.5

ENV PATH=/testbed/node_modules/.bin:/testbed/.adverbug_jest_runtime/node_modules/.bin:${PATH}

WORKDIR /testbed
CMD ["bash"]
