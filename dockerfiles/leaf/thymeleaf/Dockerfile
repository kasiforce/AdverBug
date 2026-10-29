FROM maven:3.9.11-eclipse-temurin-17

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC LANG=C.UTF-8 LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/adver-venv \
    && /opt/adver-venv/bin/pip install --no-cache-dir openai==3.8.0
ENV PATH="/opt/adver-venv/bin:${PATH}"

WORKDIR /testbed
ENV THYMELEAF_TEST_MODULES=tests/thymeleaf-tests-core,tests/thymeleaf-tests-spring5,tests/thymeleaf-tests-spring6,tests/thymeleaf-tests-springsecurity5,tests/thymeleaf-tests-springsecurity6
COPY dockerfiles/leaf/thymeleaf/deepseek-test-dependencies.patch /tmp/deepseek-test-dependencies.patch
RUN git init . \
    && git remote add origin https://github.com/thymeleaf/thymeleaf.git \
    && git -c http.version=HTTP/1.1 fetch --depth=1 origin 166b77f666d38ffb8b02220e727496d70ff77136 \
    && git checkout --detach FETCH_HEAD \
    && git remote remove origin \
    && git apply /tmp/deepseek-test-dependencies.patch \
    && mvn -B -ntp clean -pl "$THYMELEAF_TEST_MODULES" -am -DskipTests -Dmaven.javadoc.skip=true install

CMD ["sh", "-c", "mvn -B -ntp clean -pl \"$THYMELEAF_TEST_MODULES\" -am test"]
