# HS1. The Space image when the source is hidden (deploy.sh HIDDEN_SOURCE=1).
#
# Why: a public Space shows every file it is given (the Files tab, every past commit), and anyone
# can pull a public Docker Space's image (registry.hf.space). So this image carries no code of
# ours: only Python, the same system packages as the main Dockerfile, and the third-party
# dependencies (requirements.txt, names and versions only, written by deploy.sh from
# pyproject.toml). start.sh downloads the code at start, from a private repository, with a
# read-only token kept as a Space secret. A copy of this image run anywhere else has no token
# and no code.
#
# It mirrors the main Dockerfile's runtime stage line for line (user, paths, port, health), so
# the Space behaves exactly as before; the Studio's React build comes pre-built with the source.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash git git-lfs wget curl procps ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt start.sh ./
RUN pip install --no-cache-dir -r requirements.txt "huggingface_hub>=0.34"
RUN useradd --create-home --uid 1000 wardrobe \
    && mkdir -p /data/wardrobe /app/src \
    && chown -R wardrobe:wardrobe /data/wardrobe /app \
    && chmod +x /app/start.sh
USER wardrobe
ENV WARDROBE_STORAGE_ROOT=/data/wardrobe \
    WARDROBE_ENGINE=native
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status==200 else 1)"
CMD ["/app/start.sh"]
