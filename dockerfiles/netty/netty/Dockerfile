FROM rust:1.90-bookworm AS rust-toolchain

FROM maven:3.9.11-eclipse-temurin-11

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    MAVEN_OPTS=-Xmx2g

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential autoconf automake libtool cmake ninja-build cargo \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 ships Rust 1.75, but the pinned Quiche revision requires a
# newer Cargo/Rust edition. Copy a pinned official toolchain without relying
# on static.rust-lang.org, which is unavailable in some build environments.
COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup
ENV PATH=/usr/local/cargo/bin:$PATH \
    RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    CARGO_REGISTRIES_CRATES_IO_INDEX=sparse+https://rsproxy.cn/index/ \
    CARGO_NET_RETRY=10 \
    CARGO_HTTP_TIMEOUT=120
RUN mkdir -p /usr/local/cargo \
    && printf '%s\n' \
        '[source.crates-io]' \
        'replace-with = "rsproxy-sparse"' \
        '[source.rsproxy-sparse]' \
        'registry = "sparse+https://rsproxy.cn/index/"' \
        '[net]' \
        'git-fetch-with-cli = true' \
        > /usr/local/cargo/config.toml

# Use a Maven mirror that is reachable in the benchmark environment.
RUN mkdir -p /root/.m2 \
    && printf '%s\n' \
        '<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 https://maven.apache.org/xsd/settings-1.0.0.xsd">' \
        '  <mirrors><mirror><id>aliyun</id><mirrorOf>*</mirrorOf><url>https://maven.aliyun.com/repository/public</url></mirror></mirrors>' \
        '</settings>' \
        > /root/.m2/settings.xml

WORKDIR /testbed
RUN git init . \
    && git remote add origin https://github.com/netty/netty.git \
    && git -c http.version=HTTP/1.1 fetch --depth=1 origin 103787ebe8e72e66806193740ad90a23fb324043 \
    && git checkout --detach FETCH_HEAD \
    && git remote remove origin

# GoogleSource is not reachable in some build environments.  The GitHub
# repository is Google's official mirror and contains the same pinned commit.
RUN mvn -B -ntp -T 1C -DskipTests \
        -Dmaven.wagon.http.retryHandler.count=10 \
        -pl '!codec-native-quic,!codec-http3,!all,!testsuite-jpms,!testsuite-native,!testsuite-native-image,!testsuite-native-image-client,!testsuite-native-image-client-runtime-init,!testsuite-karaf,!testsuite-osgi,!testsuite-shading,!microbench,!example' -am install

CMD ["mvn", "-B", "-ntp", "-T", "1C", "-Dmaven.wagon.http.retryHandler.count=10", "-Dtest=!OpenSsl*", "-pl", "!codec-native-quic,!codec-http3,!all,!testsuite-jpms,!testsuite-native,!testsuite-native-image,!testsuite-native-image-client,!testsuite-native-image-client-runtime-init,!testsuite-karaf,!testsuite-osgi,!testsuite-shading,!microbench,!example", "-am", "test"]
