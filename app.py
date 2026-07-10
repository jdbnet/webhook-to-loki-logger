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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


import re

def clean_markdown(text: str) -> str:
    """Remove Discord markdown blocks to make text more readable."""
    if not isinstance(text, str):
        return ""
    text = text.replace("```json\n", "").replace("```\n", "").replace("```", "")
    # Strip Discord bold, underline, and strikethrough formatting
    text = re.sub(r'(\*\*|__|~~)', '', text)
    return text.strip()


def discord_payload_to_log_lines(payload: dict) -> list[str]:
    """Extract log lines from a Discord-style webhook payload.
    Formats the entire payload as a single JSON string for Loki, parsing embedded JSON if possible.
    """
    if not payload:
        return []

    result = {}
    content = payload.get("content")
    if isinstance(content, str) and content.strip():
        cleaned = clean_markdown(content)
        try:
            result["content"] = json.loads(cleaned)
        except json.JSONDecodeError:
            result["content"] = cleaned

    embeds_out = []
    for embed in payload.get("embeds") or []:
        if not isinstance(embed, dict):
            continue
            
        e_out = {}
        title = embed.get("title")
        if isinstance(title, str) and title.strip():
            e_out["title"] = title.strip()
            
        description = embed.get("description")
        if isinstance(description, str) and description.strip():
            cleaned = clean_markdown(description)
            try:
                e_out["description"] = json.loads(cleaned)
            except json.JSONDecodeError:
                e_out["description"] = cleaned
                
        fields_out = {}
        for field in embed.get("fields") or []:
            if not isinstance(field, dict):
                continue
            name = field.get("name")
            value = field.get("value")
            if isinstance(name, str) and name.strip() and value is not None:
                if not isinstance(value, str):
                    value = str(value)
                cleaned_val = clean_markdown(value)
                try:
                    fields_out[name.strip()] = json.loads(cleaned_val)
                except json.JSONDecodeError:
                    fields_out[name.strip()] = cleaned_val
                    
        if fields_out:
            e_out["fields"] = fields_out
                
        if e_out:
            embeds_out.append(e_out)
            
    if embeds_out:
        result["embeds"] = embeds_out

    if not result:
        return []

    # Generate a summary message so Grafana doesn't show a blank log line
    msg_parts = []
    if "content" in result and isinstance(result["content"], str):
        msg_parts.append(result["content"])
    for e in embeds_out:
        if "title" in e:
            msg_parts.append(f"[{e['title']}]")
        if "description" in e and isinstance(e["description"], str):
            msg_parts.append(e["description"])
            
        if "fields" in e and isinstance(e["fields"], dict):
            field_parts = []
            for k, v in e["fields"].items():
                if isinstance(v, str):
                    field_parts.append(f"{k}: {v}")
                elif isinstance(v, dict) or isinstance(v, list):
                    field_parts.append(f"{k}: {json.dumps(v)}")
            if field_parts:
                msg_parts.append(" | ".join(field_parts))
            
    if msg_parts:
        result["message"] = " - ".join(msg_parts)
    else:
        result["message"] = "Discord Webhook Event"

    return [json.dumps(result)]


def push_to_loki(log_lines: list[str]) -> None:
    """Send log lines to Loki via the push API (HTTP basic auth)."""
    if not log_lines:
        return
    now_ns = str(int(time.time() * 1_000_000_000))
    values = [[now_ns, line] for line in log_lines]
    body = {
        "streams": [
            {
                "stream": {"source": "webhook", "job": "webhook-to-loki", "event": "discord"},
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
    logger.info("Sent %d line(s) to Loki, status=%d", len(log_lines), resp.status_code)


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

    logger.info("Webhook received, extracted %d line(s)", len(log_lines))
    try:
        push_to_loki(log_lines)
    except requests.RequestException as e:
        logger.exception("Failed to send %d line(s) to Loki: %s", len(log_lines), e)
        return "", 502

    return "", 204

if __name__ == '__main__':    
    app.run(host='0.0.0.0', port=5000)