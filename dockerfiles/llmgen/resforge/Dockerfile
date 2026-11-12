FROM maven:3.9-eclipse-temurin-21
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates unzip && rm -rf /var/lib/apt/lists/*
WORKDIR /testbed
RUN git clone https://github.com/Nightdawg/ResForge.git /testbed \
 && cd /testbed && git checkout --detach 9668a1dc941e4e77ef7737556c87667cc6b68bbf && git remote remove origin \
 && mvn test -q
CMD ["bash"]
