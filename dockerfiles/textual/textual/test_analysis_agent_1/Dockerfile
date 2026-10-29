# Base image specification. Defines the foundation OS and architecture for the container.
FROM --platform=linux/x86_64 ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# System dependencies installation. Installs essential tools and libraries required for development and runtime.
RUN apt update && apt install -y \
    wget \
    git \
    build-essential \
    libffi-dev \
    python3 \
    python3-pip \
    python-is-python3 \
    curl \
    locales \
    locales-all \
    software-properties-common \
    tzdata \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry for dependency and environment management.
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

# Install Miniconda for isolated Python environment management.
RUN wget 'https://repo.anaconda.com/miniconda/Miniconda3-py311_23.11.0-2-Linux-x86_64.sh' -O miniconda.sh \
    && bash miniconda.sh -b -p /opt/miniconda3 \
    && rm miniconda.sh
ENV PATH=/opt/miniconda3/bin:$PATH

# Initialize Conda and prepare environment for the project.
RUN conda init --all && conda config --append channels conda-forge
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && \
    conda create -n testbed python=3.9 -y && \
    echo 'source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed' >> /root/.bashrc"

# Set default working directory to /testbed.
WORKDIR /testbed/

# Clone the `textual` repository and checkout the specific commit.
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && \
    conda activate testbed && \
    git clone https://github.com/Textualize/textual.git /testbed && \
    cd /testbed && \
    git checkout 5e5b7ef58b8c5572c13a3ff9027d756623661495"

# Install project dependencies using Poetry.
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && \
    conda activate testbed && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi"

# Configure pre-commit hooks and other settings.
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && \
    conda activate testbed && \
    pre-commit install"