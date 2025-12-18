#!/usr/bin/env python3
"""Extract Hindi text from images using Gemini 2.0 Flash."""

import argparse
import csv
import json
import os
import time
from pathlib import Path

import google.generativeai as genai
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file")

genai.configure(api_key=GEMINI_API_KEY)

DEFAULT_INPUT_CSV = Path("inputs/image_urls.csv")
OUTPUT_FILE = Path("outputs/output.json")

# Rate limit: 10 requests per minute for free tier
REQUESTS_PER_MINUTE = 10
DELAY_BETWEEN_REQUESTS = 60 / REQUESTS_PER_MINUTE + 0.5  # ~6.5 seconds

PROMPT = """Extract ALL Hindi/Devanagari text from this image.
Return ONLY the extracted text, nothing else.
If there are multiple lines, preserve the line breaks.
If no Hindi text is found, return "NO_TEXT_FOUND"."""


def download_image(url: str) -> bytes | None:
    """Download image from URL and return bytes."""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        print(f"  Error downloading image: {e}")
        return None


def extract_text_from_image(image_bytes: bytes, max_retries: int = 3) -> str:
    """Use Gemini to extract Hindi text from image with retry logic."""
    model = genai.GenerativeModel("gemini-2.0-flash-exp")

    for attempt in range(max_retries):
        try:
            response = model.generate_content([
                PROMPT,
                {"mime_type": "image/jpeg", "data": image_bytes}
            ])
            return response.text.strip()
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait_time = 30 * (attempt + 1)  # 30s, 60s, 90s
                print(f"  Rate limited, waiting {wait_time}s before retry...")
                time.sleep(wait_time)
            else:
                raise


def load_existing_results() -> dict:
    """Load existing results from output.json if it exists."""
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Create a dict keyed by PostID for easy lookup
            return {item["PostID"]: item for item in data}
    return {}


def save_results(results: list):
    """Save results to output.json."""
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def process_images(input_csv: Path, limit: int | None = None):
    """Process images from CSV and extract text."""
    OUTPUT_FILE.parent.mkdir(exist_ok=True)

    with open(input_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if limit:
        rows = rows[:limit]

    # Load existing results
    existing = load_existing_results()
    results = []

    print(f"Processing {len(rows)} images...")

    for i, row in enumerate(rows, 1):
        post_id = row["PostID"]

        # Check if already processed
        if post_id in existing:
            print(f"[{i}/{len(rows)}] {post_id}: Already processed, skipping")
            results.append(existing[post_id])
            continue

        cdn_url = row["cdnUrl"]
        print(f"[{i}/{len(rows)}] {post_id}: Downloading...")
        image_bytes = download_image(cdn_url)

        if not image_bytes:
            print(f"  Failed to download, skipping")
            continue

        print(f"  Extracting text...")
        try:
            text = extract_text_from_image(image_bytes)

            # Build result entry with all input fields plus extracted text
            result = {
                "Date": row["Date"],
                "PostID": row["PostID"],
                "postURL": row["postURL"],
                "cdnUrl": row["cdnUrl"],
                "Views": int(row["Views"]) if row["Views"] else 0,
                "engagement": int(row["engagement"]) if row["engagement"] else 0,
                "Likes": int(row["Likes"]) if row["Likes"] else 0,
                "Shares": int(row["Shares"]) if row["Shares"] else 0,
                "Favorites": int(row["Favorites"]) if row["Favorites"] else 0,
                "Comments": int(row["Comments"]) if row["Comments"] else 0,
                "extracted_text": text
            }
            results.append(result)

            # Save after each successful extraction
            save_results(results)

            print(f"  Text: {text[:100]}..." if len(text) > 100 else f"  Text: {text}")

            # Rate limiting delay
            time.sleep(DELAY_BETWEEN_REQUESTS)
        except Exception as e:
            print(f"  Error extracting text: {e}")

    print(f"\nDone! Results saved to {OUTPUT_FILE}")
    print(f"Total entries: {len(results)}")


def main():
    parser = argparse.ArgumentParser(description="Extract Hindi text from images")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_CSV, help="Input CSV file path")
    parser.add_argument("--limit", type=int, help="Limit number of images to process")
    args = parser.parse_args()

    process_images(input_csv=args.input, limit=args.limit)


if __name__ == "__main__":
    main()
