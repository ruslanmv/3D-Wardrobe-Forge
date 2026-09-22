#!/usr/bin/env sh
set -eu

: "${HF_SPACE_REPO:?Set HF_SPACE_REPO to org-or-user/space-name}"

echo "This helper assumes you are already authenticated with the Hugging Face CLI."
echo "Uploading repository contents to space: ${HF_SPACE_REPO}"
hf upload "${HF_SPACE_REPO}" . . --repo-type=space
