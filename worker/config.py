"""Centralized configuration for the Job Butler background worker."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorkerConfig:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "")
    )
    lm_studio_base_url: str = field(
        default_factory=lambda: os.getenv(
            "LM_STUDIO_BASE_URL", "http://host.docker.internal:1234/v1"
        ).rstrip("/")
    )
    lm_studio_api_key: str = field(
        default_factory=lambda: os.getenv("LM_STUDIO_API_KEY", "lm-studio")
    )
    lm_studio_model: str = field(
        default_factory=lambda: os.getenv("LM_STUDIO_MODEL", "qwen2.5-7b-instruct")
    )
    embedding_model_name: str = field(
        default_factory=lambda: os.getenv(
            "EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5"
        )
    )
    chroma_persist_dir: str = field(
        default_factory=lambda: os.getenv(
            "CHROMA_PERSIST_DIR", "/tmp/job_butler_chroma"
        )
    )
    r2_endpoint_url: str = field(
        default_factory=lambda: (
            os.getenv("S3_ENDPOINT_URL")
            or os.getenv("AWS_ENDPOINT_URL_S3")
            or os.getenv("R2_ENDPOINT_URL", "")
        )
    )
    r2_access_key_id: str = field(
        default_factory=lambda: (
            os.getenv("S3_ACCESS_KEY_ID")
            or os.getenv("AWS_ACCESS_KEY_ID")
            or os.getenv("R2_ACCESS_KEY_ID", "")
        )
    )
    r2_secret_access_key: str = field(
        default_factory=lambda: (
            os.getenv("S3_SECRET_ACCESS_KEY")
            or os.getenv("AWS_SECRET_ACCESS_KEY")
            or os.getenv("R2_SECRET_ACCESS_KEY", "")
        )
    )
    r2_bucket_name: str = field(
        default_factory=lambda: (
            os.getenv("S3_BUCKET_NAME")
            or os.getenv("R2_BUCKET_NAME", "job-artifacts")
        )
    )
    s3_region: str = field(
        default_factory=lambda: (
            os.getenv("S3_REGION")
            or os.getenv("AWS_REGION", "us-east-2")
        )
    )
    worker_node_id: str = field(
        default_factory=lambda: os.getenv("WORKER_NODE_ID", socket.gethostname())
    )
    queue_poll_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("QUEUE_POLL_INTERVAL_SECONDS", "10"))
    )
    llm_temperature: float = 0.1
    llm_max_context_tokens: int = 8192
    semantic_drift_threshold: float = 0.82
    bullet_max_chars: int = 170
    max_bullets_per_role: int = 4

