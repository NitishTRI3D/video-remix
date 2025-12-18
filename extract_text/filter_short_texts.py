#!/usr/bin/env python3
"""
Script to filter JSON entries with less than 16 words in extracted_text field.
"""

import json
import os
import re

def count_words(text):
    """Count words in text, handling Hindi/Devanagari and mixed scripts."""
    if not text:
        return 0
    # Split by whitespace and newlines, filter empty strings
    words = re.split(r'\s+', text.strip())
    return len([w for w in words if w])

def main():
    input_file = "/Users/nitish/Desktop/Dev/video-remix/extract_text/inputs/LoveShayari_18Dec.json"
    output_dir = "/Users/nitish/Desktop/Dev/video-remix/extract_text/outputs"
    output_file = os.path.join(output_dir, "LoveShayari_18Dec_short.json")

    # Create outputs directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Read input JSON
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Filter entries with less than 16 words
    short_entries = []
    for entry in data:
        extracted_text = entry.get("extracted_text", "")
        word_count = count_words(extracted_text)
        if word_count < 16:
            short_entries.append(entry)

    # Write filtered entries to output
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(short_entries, f, ensure_ascii=False, indent=2)

    print(f"Total entries: {len(data)}")
    print(f"Entries with < 16 words: {len(short_entries)}")
    print(f"Output saved to: {output_file}")

if __name__ == "__main__":
    main()
