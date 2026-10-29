# Base image specification. Defines the foundation OS and architecture for the container
FROM --platform=linux/x86_64 ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Resolve potential GPG issues
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time

# Update system packages and install essential tools required for Java, Maven, Bazel, and Git
RUN apt update && apt install -y \
    wget \
    git \
    curl \
    zip \
    openjdk-17-jdk \
    build-essential \
    unzip \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set JAVA_HOME and update PATH for Java
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

# Download and install Maven
RUN wget https://www.us.apache.org/dist/maven/maven-3/3.3.9/binaries/apache-maven-3.3.9-bin.zip \
    && unzip apache-maven-3.3.9-bin.zip -d /opt/maven \
    && rm apache-maven-3.3.9-bin.zip
ENV MAVEN_HOME=/opt/maven/apache-maven-3.3.9
ENV PATH=$MAVEN_HOME/bin:$PATH

# Install Bazel for build operations
RUN curl -fsSL https://bazel.build/bazel-release.pub.gpg | gpg --dearmor -o /usr/share/keyrings/bazel-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/bazel-archive-keyring.gpg] https://bazel.build/release/latest apt stable" | tee /etc/apt/sources.list.d/bazel.list \
    && apt update && apt install -y bazel

# Configure Maven memory options for testing
ENV MAVEN_OPTS="-XX:MaxPermSize=2g -Xmx4g"

# Create work directory
WORKDIR /testbed/

# Clone the target repository into the /testbed directory
RUN git clone https://github.com/google/error-prone.git /testbed/

# Checkout the specified commit SHA
RUN cd /testbed/ && git reset --hard 854665b6924534eb866aa5cf5e65a3e42a506718

# Remove origin reference to prevent accidental push
RUN cd /testbed/ && git remote remove origin

# Install project-specific dependencies using Maven
RUN cd /testbed/ && mvn install -DskipTests=true

# Setup additional Java exports based on pom.xml configuration
ENV JAVA_OPTIONS="--add-exports=java.base/jdk.internal.javac=ALL-UNNAMED --add-exports=jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED"

# Ensure proper permissions for the testbed
RUN chmod -R 777 /testbed/

# Update bash profile for container initialization
RUN echo "export JAVA_HOME=$JAVA_HOME" >> /root/.bashrc && \
    echo "export PATH=$MAVEN_HOME/bin:$JAVA_HOME/bin:$PATH" >> /root/.bashrc