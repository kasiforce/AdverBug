FROM node:22-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /testbed
RUN git clone https://github.com/LEstradioto/greendefense.git /testbed \
 && cd /testbed && git checkout --detach cd6befcd165150199b07492a57294f7bab178cc5 && git remote remove origin
RUN npm install --ignore-scripts --no-audit --no-fund
RUN mkdir -p .adverbug_jest_runtime && printf '%s\n' '{"private":true}' > .adverbug_jest_runtime/package.json \
 && cd .adverbug_jest_runtime && npm install --no-save --ignore-scripts --no-audit --no-fund jest@30.2.0
ENV PATH=/testbed/node_modules/.bin:/testbed/.adverbug_jest_runtime/node_modules/.bin:${PATH}
CMD ["bash"]
