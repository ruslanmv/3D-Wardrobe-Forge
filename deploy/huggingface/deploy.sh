#!/usr/bin/env sh
set -eu

: "${HF_SPACE_REPO:?Set HF_SPACE_REPO to org-or-user/space-name}"

echo "This helper assumes you are already authenticated with the Hugging Face CLI."
echo "Uploading repository contents to space: ${HF_SPACE_REPO}"
# The avatar library is fetched and sha256-verified when the image builds, so a
# local copy (from `make library`) is 67 MB the Space has no use for.
hf upload "${HF_SPACE_REPO}" . . --repo-type=space --exclude "assets/library/*.vrm" --exclude ".git/*"

# A Space reads its configuration (sdk: docker, app_port: 8080) from the front
# matter of its root README.md. The repository README has none, so uploading it
# as-is leaves a Space that does not know it is a Docker Space. Put the Space's
# own README in its place. The Dockerfile still finds a README.md for pip.
hf upload "${HF_SPACE_REPO}" deploy/huggingface/SPACE_README.md README.md --repo-type=space
