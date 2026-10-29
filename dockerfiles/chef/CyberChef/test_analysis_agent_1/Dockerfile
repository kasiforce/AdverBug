# Base image specification. Defines the foundation OS and architecture for the container (Required)
FROM --platform=linux/x86_64 ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# System dependencies installation. Installs essential tools and libraries required for development and runtime
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time && \
    apt update && apt install -y \
    wget \
    git \
    build-essential \
    curl \
    locales \
    locales-all \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set up locale environment variables for consistent behavior
RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Install Node.js version 24 via nvm
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.5/install.sh | bash
ENV NVM_DIR=/root/.nvm
ENV NODE_VERSION=24
ENV PATH=$NVM_DIR/versions/node/v$NODE_VERSION/bin:$PATH
RUN bash -c "source $NVM_DIR/nvm.sh && nvm install $NODE_VERSION && nvm use $NODE_VERSION"

# Install project dependencies globally for the container. Also install grunt-cli for the build process.
RUN npm install -g grunt-cli

# Set default work directory to testbed (Required)
WORKDIR /testbed/

# Target Project setup. Clone the source code, checkout to the target commit, configure it, and install project-specific dependencies
RUN git clone https://github.com/gchq/CyberChef.git /testbed/ && \
    cd /testbed/ && \
    git reset --hard cc70a4530b86aff4bc40ccc74b1ad4857eccdca2 && \
    npm install

# Update bashrc to include nvm and path setup for Node.js version 24
RUN echo 'export NVM_DIR=/root/.nvm' >> /root/.bashrc
RUN echo 'export PATH=$NVM_DIR/versions/node/v$NODE_VERSION/bin:$PATH' >> /root/.bashrc