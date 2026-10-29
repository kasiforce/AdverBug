FROM maven:3.9.11-eclipse-temurin-11

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC LANG=C.UTF-8 LC_ALL=C.UTF-8 MAVEN_OPTS=-Xmx2g

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testbed
RUN git init . \
    && git remote add origin https://github.com/apache/pdfbox.git \
    && git -c http.version=HTTP/1.1 fetch --depth=1 origin c8ab655799cb0a2f15d8e9622a1a7a678fddf46e \
    && git checkout --detach FETCH_HEAD \
    && git remote remove origin \
    && mvn -B -ntp -DskipTests install

# Apache's issue tracker occasionally times out while test fixtures are being
# downloaded. Each retry reuses every fixture fetched by earlier attempts.
CMD ["sh", "-c", "attempt=1; until mvn -B -ntp test; do [ \"$attempt\" -ge 10 ] && exit 1; attempt=$((attempt + 1)); echo \"Retrying PDFBox tests (attempt $attempt/10)\"; done"]
