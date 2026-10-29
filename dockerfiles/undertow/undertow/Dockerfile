# Undertow requires Java 17.  Maven's official Temurin image supplies both
# tools directly; no Python/Conda environment is needed for this Java project.
FROM maven:3-eclipse-temurin-17

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LANGUAGE=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    MAVEN_OPTS=-Xmx1g

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates locales tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed

# Pin the benchmark to the exact source revision used for function extraction.
RUN git clone https://github.com/undertow-io/undertow.git . \
    && git checkout --detach 77dc917cea6f40468ea481e1bafa7e15657eb887 \
    && git remote remove origin

# Compile the project and test sources while caching all Maven dependencies.
RUN mvn -B -ntp clean install -DskipTests -Dmaven.javadoc.skip=true
