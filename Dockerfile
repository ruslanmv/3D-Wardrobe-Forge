# API / native-engine image.
#
# Deliberately Blender-free: the native engine needs only Python, so the API
# container stays small and starts fast. Heavy geometry work goes to the
# Blender worker image (Dockerfile.blender).
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY wardrobe ./wardrobe
COPY worker ./worker
COPY assets ./assets

RUN pip install --no-cache-dir ".[preview,s3,redis]"

# The worker parses untrusted user models, so it does not run as root.
RUN useradd --create-home --uid 10001 wardrobe \
    && mkdir -p /data/wardrobe \
    && chown -R wardrobe:wardrobe /data/wardrobe /app
USER wardrobe

ENV WARDROBE_STORAGE_ROOT=/data/wardrobe \
    WARDROBE_ENGINE=native

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
