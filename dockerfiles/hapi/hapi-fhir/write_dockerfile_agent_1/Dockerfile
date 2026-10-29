# Use Ubuntu base image (reliable and includes bash)
FROM --platform=linux/x86_64 ubuntu:22.04

# Set non-interactive mode for apt and other installations
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Resolve potential APT GPG issues
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# Update system and install necessary tools & dependencies
RUN apt update && apt install -y \
    wget \
    git \
    curl \
    unzip \
    build-essential \
    openjdk-11-jdk \
    maven \
    locales \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Configure locales for UTF-8 compatibility
RUN locale-gen en_US.UTF-8 && update-locale LANG=en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Set JAVA_HOME environment variable
ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

# Install required Maven dependencies and set Maven cache folder
ARG MAVEN_CACHE_FOLDER=/root/.m2/repository

# Set working directory inside the container
WORKDIR /testbed/

# Clone the target repository and checkout the specified commit SHA
RUN git clone https://github.com/hapifhir/hapi-fhir.git /testbed && \
    cd /testbed && \
    git reset --hard fe490d72cf99d402df7421503572cd6550cb1a8e && \
    git remote remove origin

# Run Maven commands to install the project's dependencies without running tests
RUN mvn clean install -e -B -Dmaven.repo.local=$MAVEN_CACHE_FOLDER -DskipTests -P JACOCO,CI

# Set the Maven cache folder explicitly
ENV MAVEN_OPTS="-Dmaven.repo.local=$MAVEN_CACHE_FOLDER"

# Add a Maven wrapper script for convenience
RUN echo "export MAVEN_OPTS='-Dmaven.repo.local=$MAVEN_CACHE_FOLDER'" >> /root/.bashrc