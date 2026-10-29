# Use Ubuntu 22.04 as the base image with Bash support
FROM --platform=linux/x86_64 ubuntu:22.04

# Set build arguments and environment variables
ARG DEBIAN_FRONTEND=noninteractive
ARG FAKE_DATE
ENV TZ=Etc/UTC
ENV FAKE_SYSTEM_DATE=${FAKE_DATE}

# Fix GPG problems for apt
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# Install essential system tools, development dependencies, and locales
RUN apt update && apt install -y \
    git \
    wget \
    curl \
    build-essential \
    tzdata \
    locales \
    locales-all \
    openjdk-11-jdk \
    openjdk-17-jdk \
    maven \
    nodejs \
    npm \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Set permissions for Docker CLI usage
RUN usermod -aG docker $(whoami)

# Set up the default locale
RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Verify the Node.js and npm versions meet the prerequisites
RUN node -v && npm -v

# Maven setup: Adjust memory settings and wrapper permissions
RUN mkdir -p ~/.m2 && chmod -R 777 ~/.m2

# Define the working directory for the project
WORKDIR /testbed/

# Clone the target repository and checkout to the specified commit
RUN git clone https://github.com/apache/tinkerpop.git /testbed && \
    cd /testbed && \
    git reset --hard 3001c22f3b2c94ec111e98c0296135552a09aca8 && \
    git remote remove origin

# Install project-specific dependencies using Maven and Node.js
# Skip tests to set up the environment efficiently
RUN mvn clean install -DskipTests && npm install

# Set up environment configurations and PATH adjustments
ENV PATH=/testbed/bin:$PATH

# Ensure the required Java versions are available for execution and testing
ENV JAVA_HOME_11=/usr/lib/jvm/java-11-openjdk-amd64
ENV JAVA_HOME_17=/usr/lib/jvm/java-17-openjdk-amd64
ENV JAVA_HOME=${JAVA_HOME_17}

# Configure Maven build directory and JVM arguments for the tests
ENV MAVEN_OPTS="-Dlogback.configuration=file:target/test-classes/logback-test.xml \
                -Dlog4j.configuration=file:target/test-classes/log4j-test.properties \
                -Dslf4j.provider=ch.qos.logback.classic.spi.LogbackServiceProvider \
                -Dbuild.dir=${project.build.directory} \
                -Dis.testing=true \
                -Djava.net.preferIPv4Stack=true"

# Ensure Maven and NPM are accessible
RUN echo "export PATH=$PATH" >> /root/.bashrc && \
    echo "export MAVEN_OPTS='$MAVEN_OPTS'" >> /root/.bashrc