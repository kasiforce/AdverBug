# Use an Ubuntu base image with Bash installed
FROM --platform=linux/x86_64 ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# Install essential system tools and development dependencies
RUN apt update && apt install -y \
    wget \
    curl \
    git \
    unzip \
    build-essential \
    openjdk-11-jdk \
    locales \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Configure locale and timezone
RUN locale-gen en_US.UTF-8 && update-locale LANG=en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Install SDKMAN for managing Java versions
RUN curl -s "https://get.sdkman.io" | bash
ENV SDKMAN_DIR=/root/.sdkman
ENV PATH=${SDKMAN_DIR}/bin:${SDKMAN_DIR}/candidates/java/current/bin:$PATH

# Refresh SDKMAN and install Java versions (JDK 8, 9, 21)
RUN bash -c "source $SDKMAN_DIR/bin/sdkman-init.sh && \
    sdk env install && \
    sdk install java $(sdk list java | grep -Eo -m1 '9\\b\\.[ea|0-9]{1,2}\\.[0-9]{1,2}-open') \
    && sdk install java $(sdk list java | grep -Eo -m1 '21\\b\\.[ea|0-9]{1,2}\\.[0-9]{1,2}-open')"

# Install Gradle (needed for building and testing the project)
RUN apt update && apt install -y gradle && rm -rf /var/lib/apt/lists/*

# Configure WORKDIR
WORKDIR /testbed/

# Clone the repository and checkout to the specified commit
RUN git clone https://github.com/reactor/reactor-core.git /testbed/ && \
    cd /testbed/ && \
    git reset --hard 0d1a22ce5b31e4f2a4b9d2c6b29f943fcb6f2034 && \
    git remote remove origin

# Set up project dependencies using Gradle (without running tests)
RUN ./gradlew assemble --no-daemon --stacktrace

# Add gradle to PATH
ENV PATH="/testbed/.gradle/bin:$PATH"

# Set up final environment configurations to prioritize the container's JDK and Gradle
RUN echo "source ${SDKMAN_DIR}/bin/sdkman-init.sh" >> /root/.bashrc