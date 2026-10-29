# Base image specification: Use Ubuntu 22.04 for stability and compatibility
FROM --platform=linux/x86_64 ubuntu:22.04

# Set environment variables and configure APT to avoid timezone prompts during installation
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Fix potential GPG issues and avoid expiration warnings during apt updates
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# Update system packages and install essential tools and libraries for development and runtime
RUN apt update && apt install -y \
    wget \
    git \
    build-essential \
    python3 \
    python3-pip \
    python-is-python3 \
    locales \
    locales-all \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda for environment management
RUN wget 'https://repo.anaconda.com/miniconda/Miniconda3-py311_23.11.0-2-Linux-x86_64.sh' -O miniconda.sh && \
    bash miniconda.sh -b -p /opt/miniconda3 && \
    rm miniconda.sh

# Configure Miniconda and add its binaries to the PATH
ENV PATH=/opt/miniconda3/bin:$PATH
RUN conda init --all && conda config --append channels conda-forge

# Create a virtual environment named "testbed" with Python 3.12 and install required dependencies
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && \
    conda create -n testbed python=3.12 -y && \
    conda activate testbed && \
    pip install numpy>=1.26.0 \
    scipy>=1.11.4 \
    joblib>=1.4.0 \
    narwhals>=2.0.1 \
    threadpoolctl>=3.5.0 \
    matplotlib>=3.8.0 \
    scikit-image>=0.24.0 \
    pandas>=2.1.3 \
    seaborn>=0.13.0 \
    plotly>=5.24.0 \
    pytest>=7.1.2"

# Set the working directory to /testbed
WORKDIR /testbed/

# Clone the target repository into the container, checkout the specified commit, and set up the repository
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && \
    conda activate testbed && \
    git clone https://github.com/scikit-learn/scikit-learn.git /testbed && \
    chmod -R 777 /testbed && \
    cd /testbed && \
    git reset --hard d0e22aee7bbef7b310a2f08227c214ff6df9a526 && \
    git remote remove origin && \
    pip install -e ."

# Add activation command to .bashrc to ensure virtual environment is activated by default
RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" >> /root/.bashrc