"""HS1. The thin Space's requirements.txt: the third-party names and versions the main Dockerfile
installs (``pip install ".[preview,s3,redis,hf]"``), read from pyproject.toml. Names only, no code."""

import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    project = tomllib.load(handle)["project"]
extras = project.get("optional-dependencies", {})
wanted = [d for e in ("preview", "s3", "redis", "hf") for d in extras.get(e, [])]
for dep in [*project.get("dependencies", []), *wanted]:
    print(dep)
