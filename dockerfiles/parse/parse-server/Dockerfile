# Reproducible benchmark image for parse-community/parse-server.
FROM node:22-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

RUN git clone https://github.com/parse-community/parse-server.git . \
    && git checkout --detach 042da706beed93160f4c5999cea5d1ea8299a267 \
    && git remote remove origin

# Skip lifecycle scripts during dependency installation, then build explicitly.
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
