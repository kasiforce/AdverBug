FROM node:22-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /testbed
RUN git clone https://github.com/leobrqz/VibedGames-benchmark.git /testbed \
 && cd /testbed && git checkout --detach 0119784383b8aa480c7af5cfe76220323d4ea116 && git remote remove origin
RUN npm install --ignore-scripts --no-audit --no-fund
RUN mkdir -p .adverbug_jest_runtime && printf '%s\n' '{"private":true}' > .adverbug_jest_runtime/package.json \
 && cd .adverbug_jest_runtime && npm install --no-save --ignore-scripts --no-audit --no-fund jest@30.2.0
ENV PATH=/testbed/node_modules/.bin:/testbed/.adverbug_jest_runtime/node_modules/.bin:${PATH}
CMD ["bash"]
