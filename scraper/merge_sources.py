#!/usr/bin/env python3
"""Merge one product source JSON file into another without dropping either set."""

import json
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_url(source: dict) -> str:
    return urllib.parse.urldefrag(source.get("url", ""))[0].rstrip("/")


def load(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": "1.0", "updated_at": None, "products": {}}
    return json.loads(path.read_text())


def merge(source_path: Path, target_path: Path) -> dict:
    source_data = load(source_path)
    target_data = load(target_path)
    target_products = target_data.setdefault("products", {})

    for product_id, incoming_sources in source_data.get("products", {}).items():
        existing_sources = target_products.setdefault(str(product_id), [])
        by_url = {normalized_url(s): s for s in existing_sources if normalized_url(s)}
        for source in incoming_sources:
            key = normalized_url(source)
            if not key:
                continue
            if key in by_url:
                by_url[key].update({k: v for k, v in source.items() if v is not None})
            else:
                existing_sources.insert(0, source)
                by_url[key] = source

    target_data["updated_at"] = now_iso()
    target_path.write_text(json.dumps(target_data, indent=2) + "\n")
    return target_data


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python scraper/merge_sources.py SOURCE_JSON TARGET_JSON")
        return 2

    merged = merge(Path(sys.argv[1]), Path(sys.argv[2]))
    products = merged.get("products", {})
    print(f"products_with_sources: {sum(1 for v in products.values() if v)}")
    print(f"total_sources: {sum(len(v) for v in products.values())}")
    print(f"domyown_sources: {sum(1 for v in products.values() for s in v if s.get('retailer') == 'domyown')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
