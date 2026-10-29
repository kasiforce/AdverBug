# Use Ubuntu as the base image to ensure compatibility with Java and Maven
FROM --platform=linux/x86_64 ubuntu:22.04

# Use noninteractive terminal during image build
ARG DEBIAN_FRONTEND=noninteractive

# Set timezone for the container
ENV TZ=Etc/UTC

# Fake system date for handling potential GPG expiration issues during apt updates
ARG FAKE_DATE
ENV FAKE_SYSTEM_DATE=${FAKE_DATE}
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# Install system dependencies
RUN apt update && apt install -y \
    wget \
    curl \
    git \
    build-essential \
    openjdk-8-jdk \
    maven \
    locales \
    locales-all \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Configure locale settings  
ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8    

# Set memory requirements necessary for Maven builds
ENV MAVEN_OPTS="-Xmx512m -XX:MaxPermSize=256m"

# Set Java version and ensure Java 8 (OpenJDK) is used
ENV JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
ENV PATH="$JAVA_HOME/bin:$PATH"

# Set the working directory
WORKDIR /testbed/

# Clone the target repository and checkout the specified commit
RUN git clone https://github.com/haraldk/TwelveMonkeys.git /testbed/ && \
    cd /testbed/ && \
    git reset --hard 5fdb40d2098f9e737066d4711418f9f63a9deadf && \
    git remote remove origin

# Install Maven dependencies required by the project
RUN mvn install

# Set up testing environment configurations in .bashrc
RUN echo 'export MAVEN_OPTS="-Xmx512m -XX:MaxPermSize=256m"' >> /root/.bashrc