FROM maven:3.9-eclipse-temurin-17
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates xvfb xauth \
 && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends libxtst6 libxi6 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /testbed
RUN git clone https://github.com/nbplugins/NetbeansPluginClaudeCodeGui.git /testbed \
 && cd /testbed && git checkout --detach 019dc63e8da821126ca610461f5765286f2bfa4f && git remote remove origin \
 && sh -c 'Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/tmp/xvfb-build.log 2>&1 & DISPLAY=:99 mvn test -q'
COPY entrypoint.sh /usr/local/bin/adverbug-entrypoint
RUN chmod +x /usr/local/bin/adverbug-entrypoint
ENTRYPOINT ["/usr/local/bin/adverbug-entrypoint"]
CMD ["bash"]
