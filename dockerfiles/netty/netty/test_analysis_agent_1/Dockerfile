# Use Ubuntu 22.04 as the base image for stability and compatibility
FROM ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive
ARG FAKE_DATE
ENV TZ=Etc/UTC
ENV FAKE_SYSTEM_DATE=${FAKE_DATE}

# Prevent GPG time-based errors during apt operations
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# Update and install necessary system dependencies
RUN apt update && apt install -y \
    git \
    wget \
    curl \
    build-essential \
    openjdk-8-jdk \
    openjdk-11-jdk \
    maven \
    autoconf \
    automake \
    libtool \
    locales \
    locales-all \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set locale to ensure correct encoding handling
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Set up a virtual environment via Miniconda for robust environment isolation
RUN wget 'https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh' -O miniconda.sh \
    && bash miniconda.sh -b -p /opt/miniconda3 \
    && rm miniconda.sh
ENV PATH=/opt/miniconda3/bin:$PATH

# Initialize conda and create the testbed environment with required tools
RUN conda init bash \
    && conda config --append channels conda-forge \
    && conda create -n testbed python=3.8 -y \
    && conda activate testbed \
    && pip install pytest junitparser typing_extensions

# Set the default working directory inside the container
WORKDIR /testbed/

# Clone and set up the target project repository
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && \
    conda activate testbed && \
    git clone https://github.com/netty/netty.git /testbed && \
    cd /testbed && \
    git reset --hard 103787ebe8e72e66806193740ad90a23fb324043 && \
    git remote remove origin && \
    chmod -R 777 /testbed && \
    mvn install -DskipTests"

# Configure Maven options for memory optimization and speed
ENV MAVEN_OPTS="-Xmx1024m -XX:+TieredCompilation -XX:TieredStopAtLevel=1"

# Add conda activation to the bash profile for interactive shell sessions
RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" >> /root/.bashrc