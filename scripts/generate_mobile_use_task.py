#!/usr/bin/env python3
"""Generate a concrete mobile_use task prompt for a product search term."""
import argparse
import json
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_FILE = BASE_DIR / "config" / "mobile_use_templates.json"
CATEGORIES_FILE = BASE_DIR / "config" / "categories.json"
OUTPUT_DIR = BASE_DIR / "data" / "mobile_use_tasks"


def load_json(path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def now_iso():
    return datetime.now().isoformat()


def slug(text):
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(text)).strip("_")


def find_product(product_id_or_name):
    data = load_json(CATEGORIES_FILE)
    target = str(product_id_or_name).lower()
    for category_name, category in (data.get("categories") or {}).items():
        for item in category.get("items") or []:
            names = [item.get("id"), item.get("name")] + (item.get("search_keywords") or [])
            if any(str(name or "").lower() == target for name in names):
                return {
                    "category": category_name,
                    "product_id": item.get("id"),
                    "product_name": item.get("name"),
                    "search_term": (item.get("search_keywords") or [item.get("name")])[0],
                }
    return None


def build_task(search_term, product=None):
    templates = load_json(TEMPLATE_FILE)
    prompt = templates.get("combined_template", "").format(search_term=search_term)
    return {
        "version": "1.0.0",
        "generated_at": now_iso(),
        "product": product or {},
        "search_term": search_term,
        "condition": templates.get("condition_profile", {}),
        "timeout_seconds": templates.get("timeout_seconds", 90),
        "prompt": prompt,
        "tasks": templates.get("tasks", {}),
        "write_back_contract": templates.get("write_back_contract", {}),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", help="Product id or exact product/search name from config/categories.json")
    parser.add_argument("--search-term", help="Explicit search term, overrides --product keywords")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    product = find_product(args.product) if args.product else None
    search_term = args.search_term or (product or {}).get("search_term")
    if not search_term:
        raise SystemExit("--search-term is required when --product cannot be resolved")

    task = build_task(search_term, product)
    output = Path(args.output_dir) / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug(search_term)}.json"
    save_json(output, task)
    print(json.dumps({
        "ok": True,
        "output": str(output.resolve()),
        "search_term": search_term,
        "timeout_seconds": task["timeout_seconds"],
        "prompt": task["prompt"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
