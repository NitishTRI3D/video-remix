#!/usr/bin/env python3
"""Extract Hindi text from images using Gemini 2.0 Flash."""

import argparse
import csv
import json
import os
import time
from pathlib import Path
import base64
from io import BytesIO

import requests
from PIL import Image
from google.oauth2 import service_account
from google.auth.transport.requests import Request

# Configuration
PROJECT_ID = "prj-sc-s-video-genai-services"
LOCATION = "us-central1"
GEMINI_MODEL = "gemini-2.0-flash"
SERVICE_ACCOUNT_FILE = Path(__file__).parent / "service_account.json"

# Auth
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_credentials = None

def get_credentials():
    """Get or refresh service account credentials."""
    global _credentials
    
    if _credentials is None:
        if not SERVICE_ACCOUNT_FILE.exists():
            raise FileNotFoundError(f"Service account key not found: {SERVICE_ACCOUNT_FILE}")
        
        _credentials = service_account.Credentials.from_service_account_file(
            str(SERVICE_ACCOUNT_FILE),
            scopes=SCOPES
        )
    
    if _credentials.expired or not _credentials.token:
        _credentials.refresh(Request())
    
    return _credentials

def get_auth_headers():
    """Get auth headers for API calls."""
    creds = get_credentials()
    if creds.expired or not creds.token:
        creds.refresh(Request())
    return {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }

DEFAULT_INPUT_CSV = Path("inputs/image_urls.csv")
OUTPUT_FILE = Path("outputs/output.json")

# Rate limit: Vertex AI has higher limits
REQUESTS_PER_MINUTE = 60  # Vertex AI allows more requests
DELAY_BETWEEN_REQUESTS = 1  # 1 second delay

PROMPT = """Extract ALL Hindi/Devanagari text from this image.
Return ONLY the extracted text, nothing else.
If there are multiple lines, preserve the line breaks.
If no Hindi text is found, return "NO_TEXT_FOUND"."""


def resize_image(image_bytes: bytes, max_size: int = 1024) -> bytes:
    """Resize image if larger than max_size (in KB)."""
    # Check if resizing is needed
    if len(image_bytes) < max_size * 1024:  # Convert KB to bytes
        return image_bytes
    
    # Open image
    img = Image.open(BytesIO(image_bytes))
    
    # Convert RGBA to RGB if needed
    if img.mode == 'RGBA':
        rgb_img = Image.new('RGB', img.size, (255, 255, 255))
        rgb_img.paste(img, mask=img.split()[3])
        img = rgb_img
    
    # Start with original size
    width, height = img.size
    quality = 85
    
    while True:
        # Save to bytes
        output = BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        output_bytes = output.getvalue()
        
        # Check size
        if len(output_bytes) < max_size * 1024:
            return output_bytes
        
        # Reduce size
        if width > 1200 or height > 1200:
            # Resize to max 1200px on longest side
            ratio = min(1200/width, 1200/height)
            width = int(width * ratio)
            height = int(height * ratio)
            img = img.resize((width, height), Image.Resampling.LANCZOS)
        else:
            # Reduce quality
            quality -= 10
            if quality < 50:
                break
    
    return output_bytes


def download_image(url: str) -> tuple[bytes, str] | tuple[None, None]:
    """Download image from URL and return bytes and mime type."""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Detect mime type from content-type header or URL
        content_type = response.headers.get('content-type', '').lower()
        if 'jpeg' in content_type or 'jpg' in content_type or url.lower().endswith(('.jpg', '.jpeg')):
            mime_type = "image/jpeg"
        elif 'png' in content_type or url.lower().endswith('.png'):
            mime_type = "image/png"
        elif 'webp' in content_type or url.lower().endswith('.webp'):
            mime_type = "image/webp"
        else:
            mime_type = "image/jpeg"  # default
            
        return response.content, mime_type
    except requests.RequestException as e:
        print(f"  Error downloading image: {e}")
        return None, None


def extract_text_from_image(image_bytes: bytes, mime_type: str = "image/jpeg", max_retries: int = 3) -> str:
    """Use Gemini to extract Hindi text from image with retry logic."""
    print("    Getting auth headers...")
    headers = get_auth_headers()
    
    # Optional: Resize image if too large
    # if len(image_bytes) > 1024 * 1024:  # If larger than 1MB
    #     print(f"    Resizing image from {len(image_bytes):,} bytes...")
    #     image_bytes = resize_image(image_bytes, max_size=800)  # Resize to max 800KB
    #     print(f"    Resized to {len(image_bytes):,} bytes")
    
    # Convert image bytes to base64
    image_b64 = base64.b64encode(image_bytes).decode('utf-8')
    print(f"    Image size: {len(image_bytes)} bytes, Base64 size: {len(image_b64)} chars")
    
    url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{GEMINI_MODEL}:generateContent"
    print(f"    API URL: {url}")

    for attempt in range(max_retries):
        try:
            # Prepare the payload
            payload = {
                "contents": [{
                    "role": "user",
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": image_b64
                            }
                        },
                        {
                            "text": PROMPT
                        }
                    ]
                }],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 2048,
                }
            }
            
            print(f"    Sending request (attempt {attempt + 1}/{max_retries})...")
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            print(f"    Response status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"  API error: {response.status_code} - {response.text[:500]}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                return "ERROR"
            
            result = response.json()
            text = result["candidates"][0]["content"]["parts"][0]["text"].strip()
            return text
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
        image_bytes, mime_type = download_image(cdn_url)

        if not image_bytes:
            print(f"  Failed to download, skipping")
            continue

        print(f"  Extracting text...")
        try:
            text = extract_text_from_image(image_bytes, mime_type)

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
