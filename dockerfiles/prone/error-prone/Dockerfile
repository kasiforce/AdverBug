FROM eclipse-temurin:21-jdk-noble AS jdk21
FROM eclipse-temurin:24-jdk-noble AS jdk24
FROM maven:3.9.11-eclipse-temurin-25

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    MAVEN_OPTS=-Xmx4g

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=jdk21 /opt/java/openjdk /opt/java/jdk21
COPY --from=jdk24 /opt/java/openjdk /opt/java/jdk24

RUN mkdir -p /root/.m2 \
    && printf '%s\n' \
        '<?xml version="1.0" encoding="UTF-8"?>' \
        '<toolchains xmlns="http://maven.apache.org/TOOLCHAINS/1.1.0">' \
        '  <toolchain>' \
        '    <type>jdk</type>' \
        '    <provides><version>21</version></provides>' \
        '    <configuration><jdkHome>/opt/java/jdk21</jdkHome></configuration>' \
        '  </toolchain>' \
        '  <toolchain>' \
        '    <type>jdk</type>' \
        '    <provides><version>24</version></provides>' \
        '    <configuration><jdkHome>/opt/java/jdk24</jdkHome></configuration>' \
        '  </toolchain>' \
        '  <toolchain>' \
        '    <type>jdk</type>' \
        '    <provides><version>25</version></provides>' \
        '    <configuration><jdkHome>/opt/java/openjdk</jdkHome></configuration>' \
        '  </toolchain>' \
        '</toolchains>' \
        > /root/.m2/toolchains.xml

WORKDIR /testbed
RUN git init . \
    && git remote add origin https://github.com/google/error-prone.git \
    && git -c http.version=HTTP/1.1 fetch --depth=1 origin 854665b6924534eb866aa5cf5e65a3e42a506718 \
    && git checkout --detach FETCH_HEAD \
    && git remote remove origin \
    && mvn -B -ntp -DskipTests install

CMD ["mvn", "-B", "-ntp", "test"]
