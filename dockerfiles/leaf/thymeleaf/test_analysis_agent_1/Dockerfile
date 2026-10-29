# Base image specification
FROM --platform=linux/x86_64 ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Handle potential GPG issues during package installation
ARG FAKE_DATE
ENV FAKE_SYSTEM_DATE=${FAKE_DATE}
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# System dependencies installation
RUN apt update && apt install -y \
    wget \
    git \
    openjdk-8-jdk \
    maven \
    locales \
    locales-all \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set up Java 8 environment
ENV JAVA_HOME /usr/lib/jvm/java-8-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

# Configure the timezone settings
RUN ln -fs /usr/share/zoneinfo/$TZ /etc/localtime && dpkg-reconfigure -f noninteractive tzdata

# Set the work directory for the project
WORKDIR /testbed/

# Target project setup: Clone, checkout specific SHA, and build Maven dependencies
RUN git clone https://github.com/thymeleaf/thymeleaf.git /testbed && \
    chmod -R 777 /testbed && \
    cd /testbed && \
    git reset --hard 166b77f666d38ffb8b02220e727496d70ff77136 && \
    git remote remove origin && \
    mvn clean install -DskipTests

# Ensure Maven is installed and link it to avoid dependency resolution issues
RUN mvn dependency:resolve && mvn dependency:tree

# Write a script to initialize the Maven environment and add it to Bash startup
RUN echo "source /etc/profile && cd /testbed && mvn clean install -DskipTests" >> /root/.bashrc