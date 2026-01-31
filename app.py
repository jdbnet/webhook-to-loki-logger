"""
Discord webhook to Loki logger.
Accepts Discord-style webhook POSTs and pushes extracted log lines to Loki (HTTP basic auth).
"""
import json
import logging
import time

from dotenv import load_dotenv
from flask import Flask, request
import os
import requests

load_dotenv()

LOKI_URL = os.environ.get("LOKI_URL")
LOKI_USERNAME = os.environ.get("LOKI_USERNAME")
LOKI_PASSWORD = os.environ.get("LOKI_PASSWORD")

for name, value in [("LOKI_URL", LOKI_URL), ("LOKI_USERNAME", LOKI_USERNAME), ("LOKI_PASSWORD", LOKI_PASSWORD)]:
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")

PUSH_URL = f"{LOKI_URL.rstrip('/')}/loki/api/v1/push"
AUTH = (LOKI_USERNAME, LOKI_PASSWORD)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def discord_payload_to_log_lines(payload: dict) -> list[str]:
    """Extract log lines from a Discord-style webhook payload (content + embeds)."""
    lines = []
    if not payload:
        return lines

    content = payload.get("content")
    if isinstance(content, str) and content.strip():
        lines.append(content.strip())

    for embed in payload.get("embeds") or []:
        if not isinstance(embed, dict):
            continue
        title = embed.get("title")
        if isinstance(title, str) and title.strip():
            lines.append(f"embed: {title.strip()}")
        description = embed.get("description")
        if isinstance(description, str) and description.strip():
            lines.append(f"embed: {description.strip()}")
        for field in embed.get("fields") or []:
            if not isinstance(field, dict):
                continue
            name = field.get("name") or ""
            value = field.get("value") or ""
            if isinstance(name, str) and isinstance(value, str):
                lines.append(f"field: {name.strip()} | {value.strip()}")

    return lines


def push_to_loki(log_lines: list[str]) -> None:
    """Send log lines to Loki via the push API (HTTP basic auth)."""
    if not log_lines:
        return
    now_ns = str(int(time.time() * 1_000_000_000))
    values = [[now_ns, line] for line in log_lines]
    body = {
        "streams": [
            {
                "stream": {"source": "webhook", "job": "webhook-to-loki"},
                "values": values,
            }
        ]
    }
    resp = requests.post(
        PUSH_URL,
        json=body,
        auth=AUTH,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()


@app.route("/health")
def health():
    """Health check for k8s/Docker (no Loki call)."""
    return "", 200


@app.route("/ready")
def ready():
    """Readiness check for k8s/Docker (no Loki call)."""
    return "", 200


@app.route("/", methods=["POST"])
def webhook():
    """Accept Discord-style webhook POST; extract content/embeds and push to Loki."""
    if request.content_type and "application/json" not in request.content_type:
        return "", 400

    try:
        payload = request.get_json(force=True, silent=False)
    except (json.JSONDecodeError, TypeError):
        return "", 400

    if payload is None:
        return "", 400

    log_lines = discord_payload_to_log_lines(payload)
    if not log_lines:
        return "", 400

    try:
        push_to_loki(log_lines)
    except requests.RequestException as e:
        logger.exception("Loki push failed: %s", e)
        return "", 502

    return "", 204

if __name__ == '__main__':    
    app.run(host='0.0.0.0', port=5000)