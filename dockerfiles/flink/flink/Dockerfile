# Base image specification. Define the foundation OS and architecture for the container.
FROM --platform=linux/x86_64 ubuntu:22.04

# Set noninteractive ARG for package installations
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Handle GPG timeout issues with apt repositories
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# System dependencies installation. The adversarial generation runner is a
# Python program even though the target benchmark itself is Java-only.
RUN apt update && apt install -y \
    wget \
    git \
    build-essential \
    maven \
    openjdk-17-jdk \
    python3 \
    python3-pip \
    locales \
    tzdata && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir openai==3.8.0

# Set default locale and timezone
RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

# Set JAVA_HOME. Maven is installed from Ubuntu's package repository.
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

# Define the default working directory in the container
WORKDIR /testbed/

# Target repository setup: Clone the repository and checkout the specific commit
RUN git clone https://github.com/apache/flink.git /testbed/ && \
    cd /testbed/ && \
    git reset --hard b245479247729620e2c4c4128b843ba56f2f42a2 && \
    git remote remove origin

# Ensure Maven dependencies are setup and project is installed in development mode
RUN ./mvnw -Dfast -Pskip-webui-build \
    -Denforcer.skip=true -Drat.skip=true -Dcheckstyle.skip=true -Dspotless.skip=true \
    -DskipTests -DskipITs clean install
