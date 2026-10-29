# Base image specification. Defines the foundation OS and architecture for the container.
FROM --platform=linux/x86_64 ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Resolve potential GPG problem and set timezone.
RUN echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99ignore-time && \
    apt update && apt install -y \
    wget \
    git \
    build-essential \
    libffi-dev \
    libbz2-dev \
    libjansson-dev \
    liblzma-dev \
    libsnappy-dev \
    libzstd-dev \
    python3 \
    python3-pip \
    python-is-python3 \
    jq \
    curl \
    locales \
    locales-all \
    tzdata \
    openjdk-11-jdk \
    openjdk-17-jdk \
    maven \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda for managing Python environments.
RUN wget 'https://repo.anaconda.com/miniconda/Miniconda3-py311_23.11.0-2-Linux-x86_64.sh' -O miniconda.sh && \
    bash miniconda.sh -b -p /opt/miniconda3 && rm miniconda.sh

# Configure conda and add it to PATH.
ENV PATH=/opt/miniconda3/bin:$PATH
RUN conda init --all && conda config --append channels conda-forge

# Create a Python virtual environment for the project.
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && conda create -n testbed python=3.10 -y"

# Install project-specific Python dependencies.
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && \
    pip install pytest uvicorn"

# Install Maven toolchain plugin and set up Java versions.
RUN mkdir -p /home/mavenuser/.m2 && \
    chown -R root:root /home/mavenuser/.m2

# Create a Maven toolchains.xml file for compatibility with JDK 11 and JDK 17.
RUN echo '<?xml version="1.0" encoding="UTF-8"?> \
    <toolchains xmlns="http://maven.apache.org/TOOLCHAINS/1.1.0"> \
        <toolchain> \
            <type>jdk</type> \
            <provides> \
                <version>[11,12)</version> \
            </provides> \
            <configuration> \
                <jdkHome>/usr/lib/jvm/java-11-openjdk-amd64</jdkHome> \
            </configuration> \
        </toolchain> \
        <toolchain> \
            <type>jdk</type> \
            <provides> \
                <version>[17,18)</version> \
            </provides> \
            <configuration> \
                <jdkHome>/usr/lib/jvm/java-17-openjdk-amd64</jdkHome> \
            </configuration> \
        </toolchain> \
    </toolchains>' > /home/mavenuser/.m2/toolchains.xml

# Ensure Maven uses the correct toolchains.
RUN update-alternatives --set java /usr/lib/jvm/java-17-openjdk-amd64/bin/java && \
    update-alternatives --set javac /usr/lib/jvm/java-17-openjdk-amd64/bin/javac

# Set work directory inside the container.
WORKDIR /testbed/

# Clone the target repository and initialize the project.
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && \
    git clone https://github.com/apache/avro.git /testbed && \
    cd /testbed && \
    git reset --hard 3a207fa6e87c535b95eafca4cf5a6ef524d77df2 && \
    git remote remove origin && \
    mvn -B install -PskipQuality -DskipTests"

# Install project-specific Python dependencies (if required for linting or type checking).
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && \
    cd /testbed && pip install -r lang/py/requirements.txt && pip install -e lang/py"

# Set up interoperability testing with Maven.
RUN /bin/bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && \
    cd lang/java/interop-data-test && mvn -B verify -Pgenerate-test-data && mvn -B verify -Pcheck-test-data"

# Add the virtual environment activation to .bashrc for persistent use.
RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" >> /root/.bashrc