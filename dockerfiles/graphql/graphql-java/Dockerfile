FROM eclipse-temurin:25-jdk-noble

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    GRADLE_USER_HOME=/root/.gradle

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed
RUN git init . \
    && git remote add origin https://github.com/graphql-java/graphql-java.git \
    && git -c http.version=HTTP/1.1 fetch --depth=1 origin 4c096208ba7203c92ed6617ddfdc35653c8aca11 \
    && git checkout --detach FETCH_HEAD \
    && git remote remove origin \
    && chmod +x gradlew \
    && ./gradlew --no-daemon testClasses

CMD ["./gradlew", "--no-daemon", "test"]
