# Use Ubuntu 22.04 as the base image to ensure Bash compatibility and stable dependency management
FROM --platform=linux/x86_64 ubuntu:22.04

# Set up ARG and ENV for non-interactive installations and timezone
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Workaround for GPG issues with apt repositories (fake date)
ARG FAKE_DATE
ENV FAKE_SYSTEM_DATE=${FAKE_DATE}
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# Update the system and install necessary runtime dependencies and tools
# Excluding Maven, which will be installed with a specific version later
RUN apt update && apt install -y \
    wget \
    git \
    openjdk-17-jdk \
    gradle \
    build-essential \
    curl \
    locales \
    locales-all \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set default locale to prevent encoding issues
RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Install Java 17 toolchain required for building and runtime
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Install Maven version 3.9.0 or higher (manually since default apt version is incompatible)
RUN wget https://downloads.apache.org/maven/maven-3/3.9.0/binaries/apache-maven-3.9.0-bin.tar.gz && \
    tar -xvzf apache-maven-3.9.0-bin.tar.gz && \
    mv apache-maven-3.9.0 /opt/maven && \
    ln -s /opt/maven/bin/mvn /usr/bin/mvn && \
    rm -f apache-maven-3.9.0-bin.tar.gz

# Confirm Maven path is included in the system path
ENV PATH="/opt/maven/bin:$PATH"

# Set Maven and Gradle configurations for optimal dependency management
RUN mkdir -p /root/.m2 /root/.gradle && chmod -R 777 /root/.m2 /root/.gradle

# Include Maven Central and additional repositories (if required by the project)
RUN echo '<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0" \
                xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 http://maven.apache.org/xsd/settings-1.0.0.xsd"> \
                <profiles> \
                  <profile> \
                    <repositories> \
                      <repository> \
                        <id>maven-central</id> \
                        <url>https://repo.maven.apache.org/maven2</url> \
                      </repository> \
                      <repository> \
                        <id>saxon-dev</id> \
                        <url>https://dev.saxonica.com/maven</url> \
                      </repository> \
                    </repositories> \
                  </profile> \
                </profiles> \
              </settings>' > /root/.m2/settings.xml

# Set default WORKDIR for the application
WORKDIR /testbed/

# Clone the target repository into the container
RUN git clone https://github.com/JSQLParser/JSqlParser.git /testbed/ && \
    cd /testbed/ && \
    git reset --hard bdf8ac31bb17b2ae76400a8ddd22a39a990dcc89 && \
    git remote remove origin

# Resolve and install Maven project dependencies
RUN mvn dependency:resolve && mvn install

# Prepare Gradle for dependency resolution and build steps
RUN gradle dependencies --stacktrace && gradle build --stacktrace

# Additional build configurations and dialects setup (if specified by the README)
RUN cd /testbed/ && mvn -Dfile.encoding=UTF-8 clean install

# Set environment variable for Maven wrapper and Gradle cache directories
ENV MVN_OPTS="-Dfile.encoding=UTF-8"
ENV GRADLE_USER_HOME=/root/.gradle

# Ensure runtime compatibility with environment variables and paths
RUN echo "JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64" >> /root/.bashrc && \
    echo "PATH=${JAVA_HOME}/bin:/opt/maven/bin:$PATH" >> /root/.bashrc

# Print end instructions for enabling runtime and testing environment
RUN echo "source /root/.bashrc" >> /root/.bashrc