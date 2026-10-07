#!/usr/bin/env python3
"""Validate collector staging JSON without publishing it."""
import argparse
import hashlib
import json
from pathlib import Path

def validate(path: Path):
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("staging root must be an object")
    if data.get("publish_allowed") is not False or data.get("no_telegram") is not True:
        raise ValueError("staging safety flags invalid")
    items = data.get("global")
    if not isinstance(items, list):
        raise ValueError("global must be an array")
    if data.get("discovered_count", len(items)) > 0 and not items:
        raise ValueError("nonzero discovered_count with empty global array")
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"global[{i}] is not an object")
        if not str(item.get("title", "")).strip():
            raise ValueError(f"global[{i}] missing title")
        if not str(item.get("source", "")).startswith(("https://", "http://")):
            raise ValueError(f"global[{i}] missing source URL")
    print(json.dumps({"file":str(path),"items":len(items),"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"validation":"PASS"},ensure_ascii=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    args = parser.parse_args()
    validate(Path(args.file))
