#!/usr/bin/env python3
"""
Fix Hindi Subtitles Script
- Adds correctly rendered Hindi subtitles with proper font
- Mixes audio (80% voice + 20% background music)
- Fixes timing synchronization
"""

import argparse
import json
import subprocess
import random
from pathlib import Path
import os
import sys

# Font options for proper Hindi rendering
FONT_OPTIONS = [
    ("/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc", "Devanagari Sangam MN"),
    ("/System/Library/Fonts/Supplemental/DevanagariMT.ttc", "Devanagari MT"),
    ("/System/Library/Fonts/Supplemental/Shree714.ttc", "Shree Devanagari 714"),
    ("/System/Library/Fonts/Supplemental/ITFDevanagari.ttc", "ITF Devanagari"),
    ("/Library/Fonts/NotoSansDevanagari-Regular.ttf", "Noto Sans Devanagari"),
    ("/Library/Fonts/Lohit-Devanagari.ttf", "Lohit Devanagari"),
    ("/System/Library/Fonts/Kohinoor.ttc", "Kohinoor Devanagari"),  # Last resort
]

# Find the first available font
FONT_PATH = None
FONT_NAME = None

for font_path, font_name in FONT_OPTIONS:
    if Path(font_path).exists():
        FONT_PATH = font_path
        FONT_NAME = font_name
        print(f"Using font: {font_name} ({font_path})")
        break

if not FONT_PATH:
    print("ERROR: No suitable Hindi font found!")
    print("Please install one of these fonts:")
    print("- Noto Sans Devanagari")
    print("- Lohit Devanagari")
    print("- Arial Unicode MS")
    sys.exit(1)

# Subtitle settings
BASE_FONT_SIZE = 56  # Base font size, will be adjusted dynamically
MAX_FONT_SIZE = 60
MIN_FONT_SIZE = 36
BORDER_COLOR = "black"
BORDER_WIDTH = 3
HORIZONTAL_MARGIN = 40  # Pixels margin on each side

# Subtitle color options
SUBTITLE_COLORS = [
    ("0xFFD700", "Gold"),
    ("0xFFFFFF", "White"),
    ("0x00FFFF", "Cyan"),
    ("0xFF69B4", "Pink"),
    ("0x98FB98", "Pale Green"),
    ("0xFFA500", "Orange"),
    ("0xE6E6FA", "Lavender"),
    ("0xF0E68C", "Khaki"),
    ("0x87CEEB", "Sky Blue"),
    ("0xFFB6C1", "Light Pink"),
]


def get_random_subtitle_color():
    """Get a random subtitle color."""
    color, name = random.choice(SUBTITLE_COLORS)
    return color, name


def calculate_font_size(text: str, video_width: int = 1080) -> int:
    """Calculate appropriate font size based on text length and video width."""
    # Rough estimation: average character width is about 0.6 * font_size
    # Account for margin on both sides
    available_width = video_width - (2 * HORIZONTAL_MARGIN)
    
    # Start with base font size
    font_size = BASE_FONT_SIZE
    
    # Estimate text width (this is approximate, actual width depends on font)
    # For Devanagari, characters are wider, so use 0.7 multiplier
    estimated_width = len(text) * font_size * 0.7
    
    # Adjust font size if text is too wide
    if estimated_width > available_width:
        font_size = int(available_width / (len(text) * 0.7))
        font_size = max(MIN_FONT_SIZE, min(font_size, MAX_FONT_SIZE))
    
    return font_size


def mix_audio_streams(video_path: str, voice_audio: str, bg_audio: str, output_path: str) -> bool:
    """Mix voice audio (80%) with background audio (20%) and add to video."""
    if not bg_audio or not Path(bg_audio).exists():
        # No background audio, just use voice
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", voice_audio,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path
        ]
    else:
        # Mix audio: voice at 80%, background at 20%
        filter_complex = (
            f"[1:a]volume=0.8[voice];"
            f"[2:a]volume=0.2[bg];"
            f"[voice][bg]amix=inputs=2:duration=first[aout]"
        )
        
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", voice_audio,
            "-i", bg_audio,
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path
        ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FFmpeg error: {result.stderr[-500:]}")
    return result.returncode == 0


def add_hindi_subtitles(video_path: str, word_timestamps: list, output_path: str, 
                       text_color: str = None, timing_offset: float = 0.0,
                       shayari_text: str = None) -> tuple[bool, str, str]:
    """
    Add synced Hindi subtitles with proper font rendering.
    Shows complete lines at once, respecting original line breaks.
    
    Args:
        video_path: Input video file
        word_timestamps: List of word timestamp dictionaries
        output_path: Output video file
        text_color: Hex color for subtitles (optional)
        timing_offset: Offset to adjust timing (positive = delay, negative = advance)
        shayari_text: Original shayari text with line breaks (optional)
    
    Returns:
        (success, color_hex, color_name) tuple
    """
    # Get random color if not specified
    if text_color is None:
        text_color, color_name = get_random_subtitle_color()
    else:
        color_name = "Custom"
        for c, n in SUBTITLE_COLORS:
            if c == text_color:
                color_name = n
                break
    
    # Apply timing offset
    adjusted_timestamps = []
    for word in word_timestamps:
        adjusted_word = word.copy()
        adjusted_word["start"] = max(0, word["start"] + timing_offset)
        adjusted_timestamps.append(adjusted_word)
    
    # Split words based on shayari text line breaks if provided
    if shayari_text and '\\n' in shayari_text:
        # Split shayari by line breaks
        lines = shayari_text.split('\\n')
        line_words_list = []
        
        # Create a list of all words from timestamps for matching
        timestamp_words = [w["word"] for w in adjusted_timestamps]
        current_ts_idx = 0
        
        for line_text in lines:
            if not line_text.strip():
                continue
                
            # Get words in this line
            line_words = line_text.strip().split()
            line_timestamps = []
            
            # Match each word in the line with timestamps
            for word in line_words:
                # Clean the word for comparison (remove quotes, punctuation at edges)
                clean_word = word.strip('"').strip("'").strip()
                
                # Find this word in remaining timestamps
                found = False
                for i in range(current_ts_idx, len(adjusted_timestamps)):
                    ts_word = adjusted_timestamps[i]["word"]
                    # Clean timestamp word for comparison
                    clean_ts_word = ts_word.strip('"').strip("'").strip('।').strip(',').strip('!').strip('.')
                    
                    # Check if words match (accounting for punctuation differences)
                    if clean_word.startswith(clean_ts_word) or clean_ts_word.startswith(clean_word):
                        line_timestamps.append(adjusted_timestamps[i])
                        current_ts_idx = i + 1
                        found = True
                        break
                
                if not found:
                    print(f"    Warning: Could not find timestamp for word: {word}")
            
            if line_timestamps:
                line_words_list.append(line_timestamps)
        
        # Use the split based on actual line breaks
        if len(line_words_list) >= 2:
            line1_words = line_words_list[0]
            line2_words = line_words_list[1]
        elif len(line_words_list) == 1:
            line1_words = line_words_list[0]
            line2_words = []
        else:
            # Fallback to default split
            mid = len(adjusted_timestamps) // 2
            line1_words = adjusted_timestamps[:mid]
            line2_words = adjusted_timestamps[mid:]
    else:
        # Default split if no shayari text provided
        mid = len(adjusted_timestamps) // 2
        line1_words = adjusted_timestamps[:mid]
        line2_words = adjusted_timestamps[mid:]
    
    filters = []
    
    # Add dark strip background
    filters.append(f"drawbox=x=0:y=(ih*0.65):w=iw:h=(ih*0.35):color=black@0.7:t=fill")
    
    # Y positions for lines
    y1 = "(h*0.70)"
    y2 = "(h*0.78)"
    
    # Calculate font sizes for each line
    line1_text = " ".join([w["word"] for w in line1_words])
    line2_text = " ".join([w["word"] for w in line2_words]) if line2_words else ""
    
    font_size1 = calculate_font_size(line1_text)
    font_size2 = calculate_font_size(line2_text) if line2_text else BASE_FONT_SIZE
    
    print(f"  Line 1 ({len(line1_text)} chars): font size {font_size1}")
    if line2_text:
        print(f"  Line 2 ({len(line2_text)} chars): font size {font_size2}")
    
    # Helper function to add complete line at once with dynamic font size
    def add_line_subtitle_sized(words, y_pos, font_size, next_line_words=None, is_first_line=False):
        if not words:
            return
            
        # Get the full line text
        full_text = " ".join([w["word"] for w in words])
        full_text = full_text.replace("'", "\\'")
        
        # Start time - first line appears immediately, others sync with speech
        if is_first_line:
            start_time = 0  # Show from the beginning
        else:
            start_time = max(0, words[0]["start"] - 0.1)  # Show 0.1s before speech
        
        # End time is when next line starts or video ends
        if next_line_words:
            end_time = next_line_words[0]["start"] - 0.1
        else:
            end_time = 8.0
        
        filters.append(
            f"drawtext=text='{full_text}':fontfile='{FONT_PATH}':fontsize={font_size}:"
            f"fontcolor={text_color}:borderw={BORDER_WIDTH}:bordercolor={BORDER_COLOR}:"
            f"x=(w-text_w)/2:y={y_pos}:enable='between(t,{start_time},{end_time})'"
        )
    
    # Add line 1 (appears immediately when video starts)
    add_line_subtitle_sized(line1_words, y1, font_size1, line2_words, is_first_line=True)
    
    # Add line 2 (and keep it visible until end)
    if line2_words:
        full_text2 = " ".join([w["word"] for w in line2_words])
        full_text2 = full_text2.replace("'", "\\'")
        start_time2 = max(0, line2_words[0]["start"] - 0.1)
        
        # Show both lines together after line 2 starts
        full_text1 = " ".join([w["word"] for w in line1_words])
        full_text1 = full_text1.replace("'", "\\'")
        
        # Line 1 stays visible with line 2 (continues from time 0)
        filters.append(
            f"drawtext=text='{full_text1}':fontfile='{FONT_PATH}':fontsize={font_size1}:"
            f"fontcolor={text_color}:borderw={BORDER_WIDTH}:bordercolor={BORDER_COLOR}:"
            f"x=(w-text_w)/2:y={y1}:enable='gte(t,{start_time2})'"
        )
        
        # Line 2 appears and stays
        filters.append(
            f"drawtext=text='{full_text2}':fontfile='{FONT_PATH}':fontsize={font_size2}:"
            f"fontcolor={text_color}:borderw={BORDER_WIDTH}:bordercolor={BORDER_COLOR}:"
            f"x=(w-text_w)/2:y={y2}:enable='gte(t,{start_time2})'"
        )
    
    filter_str = ",".join(filters)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", filter_str,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "copy",
        output_path
    ]
    
    print(f"Adding subtitles with {FONT_NAME} font...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"FFmpeg error: {result.stderr[-500:]}")
    
    return result.returncode == 0, text_color, color_name


def process_video(input_video: str, voice_audio: str, word_timestamps_file: str, 
                  bg_audio: str = None, output_path: str = None, timing_offset: float = 0.0,
                  shayari_text: str = None):
    """Process a single video with audio mixing and subtitles."""
    
    input_path = Path(input_video)
    if not input_path.exists():
        print(f"Error: Video not found: {input_video}")
        return False
    
    # Load word timestamps
    with open(word_timestamps_file, 'r', encoding='utf-8') as f:
        word_timestamps = json.load(f)
    
    print(f"Loaded {len(word_timestamps)} word timestamps")
    
    # Default output path
    if not output_path:
        output_path = input_path.parent / f"{input_path.stem}_fixed.mp4"
    
    # Temporary file for audio mixing
    temp_mixed = input_path.parent / f"{input_path.stem}_temp_mixed.mp4"
    
    # Step 1: Mix audio
    print("Mixing audio...")
    if not mix_audio_streams(str(input_video), voice_audio, bg_audio or "", str(temp_mixed)):
        print("Error: Audio mixing failed")
        return False
    
    # Step 2: Add subtitles
    print("Adding Hindi subtitles...")
    success, color_hex, color_name = add_hindi_subtitles(
        str(temp_mixed), word_timestamps, str(output_path), 
        timing_offset=timing_offset,
        shayari_text=shayari_text
    )
    
    # Cleanup
    temp_mixed.unlink(missing_ok=True)
    
    if success:
        print(f"✓ Successfully created: {output_path}")
        print(f"  Subtitle color: {color_name} ({color_hex})")
        return True
    else:
        print("Error: Subtitle addition failed")
        return False


def process_directory(directory: str, timing_offset: float = 0.0):
    """Process all videos in a directory."""
    base_dir = Path(directory)
    
    # Create output directory with _fixed suffix
    output_base_dir = base_dir.parent / f"{base_dir.name}_fixed"
    output_base_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_base_dir}")
    
    # Try to load generation config for shayari text
    shayari_map = {}
    config_file = base_dir / "generation_config.json"
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                for item in config_data:
                    item_id = item.get('id', '')
                    shayari = item.get('shayari', '')
                    if item_id and shayari:
                        shayari_map[item_id] = shayari
            print(f"Loaded shayari text for {len(shayari_map)} items")
        except Exception as e:
            print(f"Warning: Could not load generation_config.json: {e}")
    
    # Get all subdirectories
    for item_dir in sorted(base_dir.iterdir()):
        if not item_dir.is_dir():
            continue
            
        print(f"\nProcessing: {item_dir.name}")
        
        # Check for required files
        intermediate_dir = item_dir / "intermediate"
        if not intermediate_dir.exists():
            print("  Skipping - no intermediate directory")
            continue
        
        # Required files
        word_timestamps_file = intermediate_dir / "word_timestamps.json"
        human_audio = intermediate_dir / "human_audio.mp3"
        
        if not word_timestamps_file.exists():
            print("  Skipping - no word_timestamps.json")
            continue
        
        if not human_audio.exists():
            print("  Skipping - no human_audio.mp3")
            continue
        
        # Get shayari text for this item
        shayari_text = shayari_map.get(item_dir.name, None)
        if shayari_text:
            print(f"  Found shayari text with line breaks")
        
        # Create output directory for this item
        output_item_dir = output_base_dir / item_dir.name
        output_item_dir.mkdir(parents=True, exist_ok=True)
        
        # Find background audio
        audio_library = base_dir.parent.parent / "inputs" / "audio_library"
        bg_audios = list(audio_library.glob("*.mp3")) + list(audio_library.glob("*.wav"))
        bg_audio = random.choice(bg_audios) if bg_audios else None
        
        if bg_audio:
            print(f"  Using background audio: {bg_audio.name}")
        
        # Process ambient video
        ambient_video = intermediate_dir / "ambient_video.mp4"
        if ambient_video.exists():
            output_ambient = output_item_dir / "ambient_video.mp4"
            process_video(
                str(ambient_video),
                str(human_audio),
                str(word_timestamps_file),
                str(bg_audio) if bg_audio else None,
                str(output_ambient),
                timing_offset=timing_offset,
                shayari_text=shayari_text
            )
        
        # Process recital video
        recital_video = intermediate_dir / "human_recital_raw.mp4"
        if recital_video.exists():
            output_recital = output_item_dir / "recital_video.mp4"
            process_video(
                str(recital_video),
                str(human_audio),
                str(word_timestamps_file),
                str(bg_audio) if bg_audio else None,
                str(output_recital),
                timing_offset=timing_offset,
                shayari_text=shayari_text
            )


def main():
    parser = argparse.ArgumentParser(description="Fix Hindi subtitles and audio mixing")
    
    parser.add_argument("--video", type=str, help="Single video file to process")
    parser.add_argument("--audio", type=str, help="Voice audio file")
    parser.add_argument("--timestamps", type=str, help="Word timestamps JSON file")
    parser.add_argument("--bg-audio", type=str, help="Background audio file (optional)")
    parser.add_argument("--output", type=str, help="Output video path")
    parser.add_argument("--directory", type=str, help="Process all videos in directory")
    parser.add_argument("--timing-offset", type=float, default=0.0, 
                       help="Timing offset in seconds (positive = delay, negative = advance)")
    parser.add_argument("--shayari", type=str, help="Shayari text with \\n for line breaks (for single video mode)")
    
    args = parser.parse_args()
    
    if args.directory:
        # Batch processing mode
        process_directory(args.directory, args.timing_offset)
    elif args.video and args.audio and args.timestamps:
        # Single video mode
        process_video(
            args.video,
            args.audio,
            args.timestamps,
            args.bg_audio,
            args.output,
            args.timing_offset,
            args.shayari
        )
    else:
        parser.print_help()
        print("\nExamples:")
        print("  # Process single video:")
        print("  python fix_subtitles.py --video input.mp4 --audio voice.mp3 --timestamps words.json --output fixed.mp4")
        print("\n  # Process all videos in directory:")
        print("  python fix_subtitles.py --directory outputs/LoveShayari_18Dec_short")
        print("\n  # Adjust timing (delay by 0.2 seconds):")
        print("  python fix_subtitles.py --directory outputs/LoveShayari_18Dec_short --timing-offset 0.2")


if __name__ == "__main__":
    main()