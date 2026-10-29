# Base image specification. Define the foundation OS and architecture for the container.
FROM --platform=linux/x86_64 ubuntu:22.04

# Set noninteractive ARG for package installations
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Handle GPG timeout issues with apt repositories
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# System dependencies installation
RUN apt update && apt install -y \
    wget \
    git \
    build-essential \
    maven \
    openjdk-17-jdk \
    locales \
    tzdata && \
    rm -rf /var/lib/apt/lists/*

# Set default locale and timezone
RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

# Install Miniconda for isolated environment management
RUN wget 'https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh' -O miniconda.sh && \
    bash miniconda.sh -b -p /opt/miniconda3 && \
    rm -f miniconda.sh
ENV PATH="/opt/miniconda3/bin:$PATH"

# Accept Conda ToS for the required channels
RUN conda init --all && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r && \
    conda config --append channels conda-forge

# Create and activate the `testbed` environment
RUN conda create -n testbed python=3.8 -y && \
    echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" >> /root/.bashrc

# Set JAVA_HOME environment variable for Java setup
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

# Define the default working directory in the container
WORKDIR /testbed/

# Target repository setup: Clone the repository and checkout the specific commit
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && \
    conda activate testbed && \
    git clone https://github.com/apache/flink.git /testbed/ && \
    cd /testbed/ && \
    git reset --hard b245479247729620e2c4c4128b843ba56f2f42a2 && \
    git remote remove origin"

# Ensure Maven dependencies are setup and project is installed in development mode
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && \
    conda activate testbed && \
    mvn clean install -DskipTests"

# Final configuration: Set environment initialization commands
RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" >> /root/.bashrc