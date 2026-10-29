# Base image specification. Defines the foundation OS and architecture for the container (Required)
FROM --platform=linux/x86_64 ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# System dependencies installation. Installs essential tools and libraries required for development and runtime (Required)
RUN apt update && apt install -y \
    wget \
    git \
    curl \
    python3 \
    python3-pip \
    openjdk-8-jdk \
    maven \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

RUN PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install --no-cache-dir 'openai>=1,<3'

# Set environment variables for Java and Maven
ENV JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

# Set the working directory inside the container (Required)
WORKDIR /testbed/

# Clone the target repository, reset to the given commit, and remove the origin
RUN git clone https://github.com/ofdrw/ofdrw.git /testbed/ && \
    cd /testbed/ && \
    git reset --hard 84e9eb260ba6fd351ecccf08a01a40305d4af635 && \
    git remote remove origin

# Set up the project with Maven (Installing dependencies without running tests)
RUN mvn clean install -DskipTests -Dgpg.skip=true

# Ensure the Maven and Java configuration is active for future sessions
RUN echo "export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64" >> /root/.bashrc && \
    echo "export PATH=\$JAVA_HOME/bin:\$PATH" >> /root/.bashrc

# Add instructions to make sure Maven knows where settings and environments are if reused
ENV PATH="/usr/share/maven/bin:${PATH}"
