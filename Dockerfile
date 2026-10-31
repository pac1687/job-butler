# Multi-architecture Dockerfile for Job Butler Worker (arm64 Apple Silicon & amd64 x86_64)
FROM python:3.12-slim-bookworm

ARG TARGETARCH
ARG TYPST_VERSION=0.12.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME="/tmp/huggingface" \
    LM_STUDIO_BASE_URL="http://host.docker.internal:1234/v1"

WORKDIR /app

# Install system dependencies and fetch precompiled Typst musl binary for arm64 / amd64
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    xz-utils \
    fontconfig \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && case "${TARGETARCH}" in \
         arm64) TYPST_ARCH="aarch64-unknown-linux-musl" ;; \
         amd64|"") TYPST_ARCH="x86_64-unknown-linux-musl" ;; \
         *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
       esac \
    && curl -fsSL "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-${TYPST_ARCH}.tar.xz" -o /tmp/typst.tar.xz \
    && tar -xJf /tmp/typst.tar.xz -C /tmp \
    && mv /tmp/typst-${TYPST_ARCH}/typst /usr/local/bin/typst \
    && chmod +x /usr/local/bin/typst \
    && rm -rf /tmp/typst* \
    && typst --version

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

COPY worker /app/worker
COPY templates /app/templates
COPY tests /app/tests
COPY pytest.ini /app/pytest.ini

# Create non-root runtime user
RUN useradd -m -u 1000 butler && chown -R butler:butler /app
USER butler

ENTRYPOINT ["python", "-m", "worker.main"]
CMD ["--nightly"]

