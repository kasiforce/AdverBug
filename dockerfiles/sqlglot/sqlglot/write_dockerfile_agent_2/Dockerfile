# Use Ubuntu 22.04 as the base image, which includes Bash and provides consistent package management behavior
FROM --platform=linux/x86_64 ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Handle potential GPG expiration issues
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# Update and install system tools and Python-related dependencies
RUN apt update && apt install -y \
    wget \
    git \
    build-essential \
    python3 \
    python3-pip \
    python-is-python3 \
    locales \
    tzdata \
    libffi-dev \
    libtiff-dev \
    jq \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda for environment management
RUN wget 'https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh' -O miniconda.sh \
    && bash miniconda.sh -b -p /opt/miniconda3 \
    && rm miniconda.sh
ENV PATH=/opt/miniconda3/bin:$PATH

# Accept the Terms of Service for Miniconda channels to avoid build errors
RUN /opt/miniconda3/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
RUN /opt/miniconda3/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Initialize conda and set up Conda-Forge as a secondary channel
RUN conda init --all && conda config --append channels conda-forge

# Create and set up the `testbed` environment
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && \
    conda create -n testbed python=3.9 -y && \
    conda activate testbed && \
    pip install --no-cache-dir setuptools>=61.0 setuptools_scm python-dateutil ruff==0.15.6 duckdb>=0.6 pandas pandas-stubs pytz pdoc pre-commit types-python-dateutil types-pytz typing_extensions pyperf && \
    pip install 'mypy>=2.4.0' && \
    conda deactivate"

# Set the default working directory
WORKDIR /testbed/

# Clone the repository, checkout a specific commit, and install it in development mode
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && \
    conda activate testbed && \
    git clone https://github.com/tobymao/sqlglot.git /testbed && \
    cd /testbed && \
    git reset --hard caa920da583f57913311798aff2561821ea8ca01 && \
    pip install -e . && \
    make install-dev && \
    conda deactivate"

# Add environment activation to .bashrc for runtime convenience
RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" >> /root/.bashrc