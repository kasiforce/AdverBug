# TwelveMonkeys targets Java 8.  The Maven image provides a matching JDK and
# Maven installation, avoiding the unavailable/obsolete Ubuntu OpenJDK 8
# package combination used by the old Dockerfile.
FROM maven:3-eclipse-temurin-8

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LANGUAGE=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    MAVEN_OPTS=-Xmx1g

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates locales tzdata python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install --no-cache-dir 'openai>=1,<3'

WORKDIR /testbed

# Pin the benchmark to the exact source revision used for function extraction.
RUN git clone https://github.com/haraldk/TwelveMonkeys.git . \
    && git checkout --detach 5fdb40d2098f9e737066d4711418f9f63a9deadf \
    && git remote remove origin

# Compile the production and test sources and install reactor artifacts. Tests
# are run by eval.sh, so image construction remains deterministic and cached.
RUN mvn -B -ntp clean install -DskipTests -Dmaven.javadoc.skip=true
