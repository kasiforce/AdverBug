# Base image specification
FROM --platform=linux/x86_64 ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# Install essential tools and libraries required for development and runtime
RUN apt-get update && apt-get install -y \
    wget \
    git \
    build-essential \
    software-properties-common \
    curl \
    sudo \
    locales \
    locales-all \
    graphviz \
    libgraphviz-dev \
    pkg-config \
    python-is-python3 \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Set up Miniconda for Python environment management
RUN wget "https://repo.anaconda.com/miniconda/Miniconda3-py310_23.5.2-0-Linux-x86_64.sh" -O miniconda.sh && \
    bash miniconda.sh -b -p /opt/miniconda3 && \
    rm miniconda.sh
ENV PATH=/opt/miniconda3/bin:$PATH
RUN conda init --all && \
    conda config --add channels conda-forge && \
    conda config --set channel_priority strict

# Create and activate a Conda environment named 'testbed' based on supported Python versions
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && \
    conda create -n testbed python=3.9 -y"

# Use the Conda environment for all further commands
SHELL ["/bin/bash", "-c"]
ENV CONDA_ALWAYS_YES=true
ENV PATH=/opt/miniconda3/envs/testbed/bin:$PATH

# Clone the repository and checkout the specified commit
WORKDIR /testbed
RUN git clone https://github.com/py-why/dowhy.git . && \
    git reset --hard 10648f1a295cbb40fd9cdd7ce43521a6ef954078 && \
    git remote remove origin

# Install project dependencies with extras (e.g. documentation, visualization)
RUN conda activate testbed && \
    pip install --upgrade pip && \
    pip install cython scipy numpy pandas statsmodels sympy scikit-learn networkx && \
    pip install matplotlib pydot pygraphviz && \
    pip install sphinx seaborn cdt nbconvert nbsphinx IPython && \
    pip install -e .

# Add activation commands to bashrc for interactive use
RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" >> ~/.bashrc