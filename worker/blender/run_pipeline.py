"""Blender entrypoint for Wardrobe Forge."""

from __future__ import annotations

import argparse
import sys


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-avatar", required=True)
    parser.add_argument("--garment", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    print("[WardrobeForge] source:", args.input_avatar)
    print("[WardrobeForge] garment:", args.garment)
    print("[WardrobeForge] output:", args.output)
    print("[WardrobeForge] TODO: import -> analyze -> fit -> weights -> mask -> export -> reimport")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
