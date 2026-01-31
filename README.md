# Webhook to Loki Logger

Accepts Discord-style webhook POSTs and forwards the extracted content to a Loki instance (HTTP basic auth). Intended for FiveM scripts that only support Discord webhooks—point them at this service instead and logs go to Loki.

## Environment variables

| Variable        | Description                          |
|----------------|--------------------------------------|
| `LOKI_URL`     | Loki base URL (e.g. `https://loki.example.com`) |
| `LOKI_USERNAME`| HTTP basic auth username for Loki    |
| `LOKI_PASSWORD`| HTTP basic auth password for Loki    |

Copy `.env.example` to `.env` and set these values for local runs.

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env   # edit with your Loki URL and credentials
python app.py
```

The app listens on port 5000 by default.

## Running with Docker

```bash
docker run -p 5000:5000 \
  -e LOKI_URL=https://loki.example.com \
  -e LOKI_USERNAME=your_username \
  -e LOKI_PASSWORD=your_password \
  cr.jdbnet.co.uk/public/discord-to-loki:latest
```

## Usage

Send a `POST /` request with a JSON body in Discord webhook format (`content` and/or `embeds`). The service extracts the text and pushes it to Loki. Use this URL as the “webhook” target in your FiveM script instead of a Discord webhook URL.
