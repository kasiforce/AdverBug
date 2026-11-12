FROM python:3.12-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /testbed
RUN git clone https://github.com/ligenjian001-ai/pdf_commenter.git /testbed \
 && cd /testbed && git checkout --detach 5db1752849a31bc565ad0abfa067200dbf81ba5d && git remote remove origin \
 && pip install --no-cache-dir -r backend/requirements.txt pytest
CMD ["bash"]
