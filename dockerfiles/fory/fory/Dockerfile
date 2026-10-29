FROM maven:3.9.11-eclipse-temurin-17

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC LANG=C.UTF-8 LC_ALL=C.UTF-8 MAVEN_OPTS=-Xmx2g

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

# Use a reachable Maven mirror for dependency resolution.
RUN mkdir -p /root/.m2 \
    && printf '%s\n' \
        '<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 https://maven.apache.org/xsd/settings-1.0.0.xsd">' \
        '  <mirrors><mirror><id>aliyun</id><mirrorOf>*</mirrorOf><url>https://maven.aliyun.com/repository/public</url></mirror></mirrors>' \
        '</settings>' > /root/.m2/settings.xml

WORKDIR /testbed
RUN git init . \
    && git remote add origin https://github.com/apache/fory.git \
    && git -c http.version=HTTP/1.1 fetch --depth=1 origin d8ed8643ed66ab7c7874c70dea2e0a407ccfdeb6 \
    && git checkout --detach FETCH_HEAD \
    && git remote remove origin

WORKDIR /testbed/java
RUN mvn -B -ntp -DskipTests install

CMD ["mvn", "-B", "-ntp", "test"]
