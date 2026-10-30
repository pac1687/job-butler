"""Pre-flight health check verifying host LM Studio server availability (SPEC.md 3.2)."""

from __future__ import annotations

import logging
import sys
import httpx

from worker.config import WorkerConfig

logger = logging.getLogger(__name__)


def check_lm_studio_health(
    base_url: str | None = None,
    timeout_seconds: float = 5.0,
) -> bool:
    """
    Pings {base_url}/models (default http://host.docker.internal:1234/v1/models).
    Returns True if HTTP 200 and at least one model is active in the response payload.
    """
    resolved_base = (base_url or WorkerConfig().lm_studio_base_url).rstrip("/")
    models_url = f"{resolved_base}/models"

    try:
        response = httpx.get(models_url, timeout=timeout_seconds)
        if response.status_code != 200:
            logger.warning(
                "LM Studio pre-flight check failed with status %s at %s",
                response.status_code,
                models_url,
            )
            return False

        payload = response.json()
        models = payload.get("data", [])
        if not isinstance(models, list) or len(models) == 0:
            logger.warning(
                "LM Studio is reachable at %s but no models are currently loaded.",
                models_url,
            )
            return False

        model_ids = [m.get("id", "unknown") for m in models if isinstance(m, dict)]
        logger.info("LM Studio pre-flight check passed. Active models: %s", model_ids)
        return True

    except Exception as exc:
        logger.warning(
            "LM Studio server is offline or unreachable at %s (%s). Skipping batch.",
            models_url,
            exc,
        )
        return False


def enforce_preflight_or_exit(base_url: str | None = None) -> None:
    """Exits cleanly with status 0 if LM Studio is offline (per SPEC.md 3.2)."""
    if not check_lm_studio_health(base_url=base_url):
        logger.warning("Exiting cleanly with status 0 because LM Studio is offline.")
        sys.exit(0)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ok = check_lm_studio_health()
    sys.exit(0 if ok else 1)


