# Reproducible benchmark image for the CyberChef JavaScript project.
# The benchmark runs independent Jest suites; CyberChef's native tests remain
# available through npm test but are not used as the benchmark runner.
FROM node:24-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    NODE_OPTIONS=--experimental-vm-modules

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

RUN git clone https://github.com/gchq/CyberChef.git /testbed \
    && cd /testbed \
    && git checkout --detach 9a37a182c00c4ace12915ca16d0c81c15850bb61 \
    && git remote remove origin

# Skip lifecycle scripts during the first install.  CyberChef's postinstall
# performs source rewrites that are required by its Node-side modules, so run
# that project step explicitly after all files are present.
RUN npm ci --ignore-scripts --no-audit --no-fund \
    && npm run postinstall

# Jest is deliberately isolated from the project's native test framework.
RUN mkdir -p /testbed/.adverbug_jest_runtime \
    && printf '%s\n' '{"name":"adverbug-jest-runtime","private":true}' > /testbed/.adverbug_jest_runtime/package.json \
    && cd /testbed/.adverbug_jest_runtime \
    && npm install --no-save --ignore-scripts --no-audit --no-fund jest@30.0.5

ENV PATH=/testbed/node_modules/.bin:/testbed/.adverbug_jest_runtime/node_modules/.bin:${PATH}

WORKDIR /testbed
CMD ["bash"]
