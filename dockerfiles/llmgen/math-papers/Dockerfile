FROM python:3.12-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /testbed
RUN git clone https://github.com/WaschbaerImHaus/ai-generated-math-papers.git /testbed \
 && cd /testbed && git checkout --detach cf24dc26ce58031c1b37fa096e43eee40ae4c985 && git remote remove origin \
 && pip install --no-cache-dir pytest numpy sympy scipy flask
CMD ["bash"]
