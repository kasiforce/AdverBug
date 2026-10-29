# Base image specification. Defines the foundation OS and architecture for the container
FROM --platform=linux/x86_64 ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# System dependencies installation
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time
RUN apt update && apt install -y \
    wget \
    git \
    curl \
    build-essential \
    locales \
    locales-all \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set up Node.js (LTS version) and NPM
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt install -y nodejs \
    && npm install -g npm@latest \
    && npm install -g yarn \
    && npm install -g mocha \
    && rm -rf /var/lib/apt/lists/*

# Set default workdir to /testbed
WORKDIR /testbed/

# Target project setup - Clone repository and checkout the specified commit
RUN git clone https://github.com/eslint/eslint.git /testbed \
    && cd /testbed \
    && git reset --hard 8ffeb8c023bea91a5cfa01b1413a52a83838a59a \
    && git remote remove origin

# Install all runtime and development dependencies
RUN npm install \
    && npm link

# Set environment PATH to prioritize local binaries
ENV PATH=/testbed/node_modules/.bin:$PATH