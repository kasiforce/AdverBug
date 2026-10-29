FROM maven:3.9.11-eclipse-temurin-17

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC LANG=C.UTF-8 LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Use a reachable Maven mirror for dependency resolution.
RUN mkdir -p /root/.m2 \
    && printf '%s\n' \
        '<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 https://maven.apache.org/xsd/settings-1.0.0.xsd">' \
        '  <mirrors><mirror><id>aliyun</id><mirrorOf>*</mirrorOf><url>https://maven.aliyun.com/repository/public</url></mirror></mirrors>' \
        '</settings>' > /root/.m2/settings.xml

WORKDIR /testbed
RUN git init . \
    && git remote add origin https://github.com/JSQLParser/JSqlParser.git \
    && git -c http.version=HTTP/1.1 fetch --depth=1 origin bdf8ac31bb17b2ae76400a8ddd22a39a990dcc89 \
    && git checkout --detach FETCH_HEAD \
    && git remote remove origin

RUN mvn -B -ntp -DskipTests -Dfile.encoding=UTF-8 install

CMD ["mvn", "-B", "-ntp", "-Dfile.encoding=UTF-8", "test"]
