# Container image for the God's Eye dashboard server.
# Builds anywhere with Docker — Fly.io, Render, Railway, your own host.
FROM python:3.12-slim

# httpx pulls cleanly with no system deps; keep the image minimal.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install Python deps first so they cache across source-only changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the dashboard. The server reads gods-eye/index.html at request
# time and substitutes {{...}} env-var placeholders, so no build step.
COPY gods-eye/ ./gods-eye/

# Fly.io / most container hosts inject PORT; server.py honours it.
EXPOSE 8777

CMD ["python", "gods-eye/server.py"]
