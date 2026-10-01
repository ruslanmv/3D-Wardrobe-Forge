# API / native-engine image — also the Hugging Face Space image.
#
# Deliberately Blender-free: the native engine needs only Python, so the API
# container stays small and starts fast. Heavy geometry work goes to the
# Blender worker image (Dockerfile.blender).
#
# The same image serves Wardrobe Studio at /studio/ (the root redirects there).
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Nothing in this image runs these; Hugging Face does. A Docker Space with Dev
# Mode appends its own build steps to this image (`git config --global ...`, an
# OpenVSCode server, an init process), and on a slim base with no git the Space's
# build failed with "git: not found" after every one of our own steps had passed.
# These are the tools its Dev Mode documents as required in the image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash git git-lfs wget curl procps ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY wardrobe ./wardrobe
COPY worker ./worker
COPY tools ./tools
COPY assets ./assets

RUN pip install --no-cache-dir ".[preview,s3,redis]"

# The Studio's avatar library: yourfriend.online's five CC0 avatars, fetched and
# checked against the sha256 pins in assets/library/models.json. They are not in
# git (67 MB, and a Space rejects plain-git files over 10 MB). A pin mismatch
# fails the build, because an editor serving the wrong bytes is worse than none.
# FETCH_LIBRARY=0 builds an API-only image; the Studio then lists them as missing.
ARG FETCH_LIBRARY=1
RUN if [ "$FETCH_LIBRARY" = "1" ]; then python tools/fetch_library.py; fi

# The worker parses untrusted user models, so it does not run as root.
#
# uid 1000, not an arbitrary high uid: Hugging Face Docker Spaces run the
# container as uid 1000 whatever USER says. With the tree owned by anyone else,
# the process could not write /data/wardrobe and every job on a Space failed at
# its first store write. Still non-root, still a dedicated account.
RUN useradd --create-home --uid 1000 wardrobe \
    && mkdir -p /data/wardrobe \
    && chown -R wardrobe:wardrobe /data/wardrobe /app
USER wardrobe

ENV WARDROBE_STORAGE_ROOT=/data/wardrobe \
    WARDROBE_ENGINE=native

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
