# Reproducible benchmark image for eslint/eslint.
FROM node:24-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    NODE_OPTIONS=--experimental-vm-modules

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

RUN git clone https://github.com/eslint/eslint.git /testbed \
    && cd /testbed \
    && git checkout --detach b59d889c7c18d8c73144e6ba46e9e7f3e7da0196 \
    && git remote remove origin

# Do not run Cypress/browser postinstall hooks while building a headless
# benchmark image.  The source modules and their Node dependencies are still
# installed and are sufficient for generated unit tests.
RUN npm install --ignore-scripts --no-audit --no-fund

RUN mkdir -p /testbed/.adverbug_jest_runtime \
    && printf '%s\n' '{"name":"adverbug-jest-runtime","private":true}' > /testbed/.adverbug_jest_runtime/package.json \
    && cd /testbed/.adverbug_jest_runtime \
    && npm install --no-save --ignore-scripts --no-audit --no-fund jest@30.0.5

ENV PATH=/testbed/node_modules/.bin:/testbed/.adverbug_jest_runtime/node_modules/.bin:${PATH}

WORKDIR /testbed
CMD ["bash"]
