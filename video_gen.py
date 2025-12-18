#!/usr/bin/env python3
"""
Video Generation Pipeline - Generate ambient-video with human-recital audio
Based on shayari_dist pipeline but focused only on ambient video generation.

Process:
1. Generate human-recital video with veo3.1-fast (with audio)
2. Extract audio from human-recital video
3. Generate ambient-recital video with veo3.1 (without audio)
4. Mix audio: 80% human-recital + 20% random from audio_library
5. Add synced subtitles at center

APIs Used:
- Gemini 2.0 Flash - prompt generation
- Gemini 2.5 Pro - audio transcription for word timestamps
- Nano Banana (gemini-2.5-flash-image) - image generation
- Veo 3.1 - video generation

Usage:
  python video_gen.py --input inputs/test.json
  python video_gen.py --input inputs/test.json --index 0
  python video_gen.py --input inputs/test.json --force
"""

import argparse
import json
import time
import base64
import subprocess
import os
import re
import requests
import random
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from google.oauth2 import service_account
from google.auth.transport.requests import Request


# =============================================================================
# BASIC CONFIG
# =============================================================================

load_dotenv()

project_id = os.getenv("PROJECT_ID")
location = os.getenv("LOCATION", "us-central1")
PROJECT_ID = project_id
LOCATION = location

if not project_id:
    raise ValueError("PROJECT_ID is not set")
if not location:
    raise ValueError("LOCATION is not set")

# Models
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_PRO_MODEL = "gemini-2.0-flash"  # For audio transcription
IMAGE_MODEL = "gemini-2.5-flash-image"  # Nano Banana
VEO_MODEL = "veo-3.1-fast-generate-preview"


# Paths
SERVICE_ACCOUNT_FILE = Path(__file__).parent / "service_account.json"
OUTPUTS_DIR = Path(__file__).parent / "outputs"
AUDIO_LIBRARY_DIR = Path(__file__).parent / "inputs" / "audio_library"

# Rate limiting
GEMINI_DELAY = 3  # seconds between Gemini calls

# Video/Image settings
IMAGE_ASPECT_RATIO = "9:16"
VIDEO_ASPECT_RATIO = "9:16"
VIDEO_DURATION_SECONDS = 8
VIDEO_PERSON_GENERATION = "allow_adult"

# Text overlay settings
FONT_PATH = "/System/Library/Fonts/Kohinoor.ttc"
FONT_SIZE = 60  # Increased for better readability at bottom
BORDER_COLOR = "black"
BORDER_WIDTH = 3  # Thicker border for better contrast

# Subtitle color options (10 colors)
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

# =============================================================================
# DIVERSITY PARAMETERS
# =============================================================================

# Human recital character diversity
RECITAL_GENDERS = ["man", "man","man","man"]

RECITAL_AGE_GROUPS = [
    ("young", "22-28", "youthful energy, fresh face"),
    ("young", "22-28", "youthful energy, fresh face"),
    ("young", "22-28", "youthful energy, fresh face"),
    ("young", "22-28", "youthful energy, fresh face"),
    ("mature", "30-40", "confident, experienced look"),
    ("middle-aged", "42-52", "wise, contemplative expression"),
    ("elder", "55-65", "weathered, philosophical demeanor"),
]

RECITAL_VOICE_TEXTURES = [
    "soft and breathy, intimate whisper-like",
    "deep and resonant, commanding presence",
    "gentle and melodic, soothing tone",
    "raw and emotional, slightly cracked",
    "calm and measured, meditative pace",
]

RECITAL_SETTINGS = [
    "by a rain-streaked window with city lights behind",
    "in a dimly lit old library with books",
    "on a moonlit balcony with plants",
    "in a candlelit room with warm shadows",
    "by a foggy riverside at dawn",
    "in an artist's studio with paintings",
    "at a quiet café corner with steaming chai",
    "on a train, watching landscapes pass",
]

RECITAL_CLOTHING_MALE = [
    "simple white kurta",
    "dark nehru jacket over cream shirt",
    "casual linen shirt, slightly unbuttoned",
    "traditional shawl over kurta",
    "modern black t-shirt",
]

RECITAL_CLOTHING_FEMALE = [
    "elegant silk saree with subtle jewelry",
    "simple cotton kurta with dupatta",
    "modern kurti with jhumka earrings",
    "traditional salwar kameez",
    "contemporary dress with Indian accessories",
]

# Ambient video diversity
AMBIENT_SETTINGS = [
    "rooftop terrace at golden hour with city skyline",
    "rain-soaked street with neon reflections",
    "peaceful beach at sunset with waves",
    "traditional haveli courtyard with diyas",
    "misty hill station with pine trees",
    "bustling old city lane at dusk",
    "serene lake with mountains behind",
    "flower-filled garden in soft morning light",
    "vintage café with large windows",
    "temple steps at evening aarti time",
]

AMBIENT_WOMAN_APPEARANCES = [
    ("long flowing black hair", "fair complexion", "delicate features"),
    ("wavy brown hair", "dusky skin tone", "expressive eyes"),
    ("short stylish hair", "wheatish complexion", "strong jawline"),
    ("braided hair with flowers", "medium skin tone", "soft features"),
    ("curly voluminous hair", "olive complexion", "prominent cheekbones"),
]

AMBIENT_WOMAN_OUTFITS = [
    "vibrant red saree with gold border",
    "pastel blue lehenga with silver work",
    "white cotton saree with minimal jewelry",
    "modern fusion outfit - crop top and palazzo",
    "elegant black dress with traditional earrings",
    "yellow anarkali with floral print",
    "maroon silk kurta with churidar",
    "emerald green saree with temple jewelry",
]

AMBIENT_CUT_STYLES = [
    ("single", "One continuous shot with subtle camera movement"),
    ("two-cut", "[0-4s] Wide establishing shot, [4-8s] Close-up emotional shot"),
    ("three-cut", "[0-3s] Wide shot, [3-5s] Medium shot, [5-8s] Close-up"),
    ("dynamic", "[0-2s] Detail shot, [2-5s] Medium shot with movement, [5-8s] Wide pullback"),
]

def get_random_subtitle_color():
    """Get a random subtitle color."""
    color, name = random.choice(SUBTITLE_COLORS)
    return color, name

def get_random_recital_character():
    """Get random parameters for human recital character."""
    gender = random.choice(RECITAL_GENDERS)
    age_group, age_range, age_desc = random.choice(RECITAL_AGE_GROUPS)
    voice = random.choice(RECITAL_VOICE_TEXTURES)
    setting = random.choice(RECITAL_SETTINGS)
    clothing = random.choice(RECITAL_CLOTHING_MALE if gender == "man" else RECITAL_CLOTHING_FEMALE)

    return {
        "gender": gender,
        "age_group": age_group,
        "age_range": age_range,
        "age_desc": age_desc,
        "voice_texture": voice,
        "setting": setting,
        "clothing": clothing,
    }

def get_random_ambient_params():
    """Get random parameters for ambient video."""
    setting = random.choice(AMBIENT_SETTINGS)
    hair, skin, features = random.choice(AMBIENT_WOMAN_APPEARANCES)
    outfit = random.choice(AMBIENT_WOMAN_OUTFITS)
    cut_style, cut_desc = random.choice(AMBIENT_CUT_STYLES)

    return {
        "setting": setting,
        "hair": hair,
        "skin": skin,
        "features": features,
        "outfit": outfit,
        "cut_style": cut_style,
        "cut_desc": cut_desc,
    }


# =============================================================================
# PROMPT TEMPLATES
# =============================================================================

# Image prompt for human portrait (character for video) - uses diversity params
HUMAN_PORTRAIT_PROMPT_TEMPLATE = """
Create a character portrait prompt for video generation based on the given parameters.

SHAYARI:
"{shayari}"

MANDATORY CHARACTER PARAMETERS (use these EXACTLY):
- Gender: {gender}
- Age Range: {age_range} years old
- Character Feel: {age_desc}
- Voice Style: {voice_texture}
- Clothing: {clothing}
- Setting: {setting}

TASK: Generate a portrait prompt using the EXACT parameters above.
Match the emotional expression to the shayari's mood.

RULES:
1. Use the EXACT gender, age, clothing, and setting provided
2. Indian/South Asian person with varied skin tone and features
3. Clear face visibility for video generation
4. Cinematic lighting that matches the setting
5. NO text/subtitles in image

OUTPUT FORMAT (return ONLY this):
A {age_range} year old Indian {gender} with [specific hair and features], wearing {clothing}, [emotional expression matching shayari], {setting}, cinematic lighting. Portrait shot, clear face. No text in image.
""".strip()

# Ambient video prompt - uses diversity params
AMBIENT_VIDEO_PROMPT_TEMPLATE = """
Create a cinematic video prompt featuring a beautiful Indian woman with the given parameters.

SHAYARI:
"{shayari}"

MANDATORY PARAMETERS (use these EXACTLY):
- Setting/Location: {setting}
- Woman's Hair: {hair}
- Woman's Skin Tone: {skin}
- Woman's Features: {features}
- Woman's Outfit: {outfit}
- Cut Style: {cut_style}
- Cut Description: {cut_desc}

CONTEXT ANALYSIS (adjust actions based on shayari mood):
- Romantic → shy smiles, playing with hair, dreamy gazes
- Melancholic → looking away, touching face, wistful expressions
- Nostalgic → looking at photos, distant stare, gentle sighs
- Festive → lighting diyas, arranging flowers, celebratory gestures
- Longing → waiting postures, checking phone/door, hopeful glances

TASK: Generate a video prompt using the EXACT parameters above.
The woman should have {hair}, {skin}, {features}.
She wears {outfit}.
Location is {setting}.
Use the {cut_style} cut style: {cut_desc}

CINEMATIC ELEMENTS:
- Match lighting to setting and mood
- Natural, graceful movements
- Cinematic color grading
- Wind/rain/light effects where appropriate

IMPORTANT:
- NO speaking or lip movement
- Visual continuity (same woman, same outfit throughout)
- Smooth transitions if multiple cuts

OUTPUT FORMAT (return ONLY this):
Beautiful Indian woman with {hair}, {skin}, {features}, wearing {outfit}, at {setting}. {cut_desc}. [Add emotional actions matching shayari mood]. 8 seconds, 9:16 vertical, cinematic. No dialogue, no audio.
""".strip()

# Human recital video prompt (person speaking) - uses diversity params
HUMAN_VIDEO_PROMPT_INTRO_TEMPLATE = """
CRITICAL: THIS IS SPOKEN WORD ONLY. ABSOLUTELY NO SINGING.

A single Indian {gender} speaks a Hindi shayari in a FLAT, MONOTONE voice.

CHARACTER: {age_range} years old, {age_desc}
VOICE DELIVERY: {voice_texture}

MANDATORY VOICE RULES:
- SPOKEN like reading a personal diary entry or sending a voice message
- MONOTONE - no musical pitch changes, no melody whatsoever
- FLAT emotional delivery with subtle intensity in eyes only
- Natural speech rhythm with meaningful PAUSES between phrases
- NO singing, NO humming, NO melodic intonation
- NO stretching of words, NO rhythmic patterns
- Think: confessing to a friend late at night, not performing

Avoid any text/subtitles in the video.

[0:00–0:00.5] small breath, eyes settle, prepares to speak
""".strip()

HUMAN_VIDEO_PROMPT_OUTRO = """
[0:07.5–0:08.0] soft exhale, gaze drops slightly

VOICE REMINDER: Completely flat spoken delivery throughout.
- NO music, NO melody, NO singing whatsoever
- NO rhythmic stretching or musical intonation
- Plain conversational Hindi speech
- Emotion conveyed through pauses and facial expression, NOT voice melody

Visual consistency unchanged: clothing, hair, lighting, background.
Duration: 8 seconds.
""".strip()

VIDEO_TIMELINE_TEMPLATE = """
Generate ONLY the timeline portion for a VEO 3.1 video prompt.

IMPORTANT: This is SPOKEN shayari, NOT sung. Flat monotone voice like reading aloud.

TEXT TO SPEAK (exact words, do not change):
"{shayari}"

YOUR TASK:
Generate timeline entries from [0:00.5] to [0:07.5] (7 seconds total).
Split the text naturally with MEANINGFUL PAUSES between phrases.

FORMAT (follow exactly):
[0:00.5–0:XX.X] speaks flatly: "first phrase here…" monotone, no melody
[0:XX.X–0:XX.X] pause, slight breath
[0:XX.X–0:XX.X] speaks flatly: "next phrase…" same flat tone
... continue until 0:07.5

RULES:
- Each line starts with timestamp [0:XX.X–0:XX.X]
- Speech lines: "speaks flatly:" followed by Hindi text in quotes, then "monotone, no melody"
- Pause lines: "pause, slight breath" or "pause, eyes shift"
- Speech pace: ~2 words per second (slower, more deliberate)
- Include 3-4 meaningful pauses (0.4-0.6s each) for emotional weight
- Final timestamp must end at exactly 0:07.5
- Use the EXACT Hindi text provided
- NO singing instructions, NO melodic descriptions

Return ONLY the timeline lines, nothing else.
""".strip()

# Audio transcription prompt (for word timestamps)
AUDIO_TRANSCRIPTION_PROMPT = """
Listen to this Hindi audio carefully and provide word-by-word timestamps.

Return ONLY a valid JSON array with this exact format:
[
  {"word": "किसी", "start": 0.94},
  {"word": "की", "start": 1.33},
  ...
]

RULES:
1. Include every word spoken
2. Start time in seconds (decimal)
3. Preserve punctuation attached to words (like "लिए,")
4. Be precise with timestamps
5. Return ONLY the JSON array, no explanation
"""


# =============================================================================
# AUTH & UTILS
# =============================================================================

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_credentials = None


def get_timestamp_suffix() -> str:
    """Get timestamp suffix in IST 12hr format."""
    ist = ZoneInfo("Asia/Kolkata")
    now = datetime.now(ist)
    return now.strftime("%Y%m%d-%I%M%p").upper()


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


def get_random_audio_from_library() -> str:
    """Get a random audio file from the audio library."""
    if not AUDIO_LIBRARY_DIR.exists():
        print(f"  Audio library not found: {AUDIO_LIBRARY_DIR}")
        return None
    
    audio_files = list(AUDIO_LIBRARY_DIR.glob("*.mp3")) + list(AUDIO_LIBRARY_DIR.glob("*.wav"))
    if not audio_files:
        print(f"  No audio files found in {AUDIO_LIBRARY_DIR}")
        return None
    
    selected = random.choice(audio_files)
    print(f"    → Selected background audio: {selected.name}")
    return str(selected)


# =============================================================================
# GEMINI API
# =============================================================================

def call_gemini(prompt: str, model: str = None) -> str:
    """Call Gemini API to generate text."""
    model = model or GEMINI_MODEL
    headers = get_auth_headers()

    url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{model}:generateContent"

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 2048,
        }
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        raise Exception(f"Gemini API error: {response.status_code} - {response.text}")

    result = response.json()
    text = result["candidates"][0]["content"]["parts"][0]["text"].strip()

    # Clean up quotes
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]

    return text


def call_gemini_with_audio(audio_path: str, prompt: str) -> str:
    """Call Gemini 2.5 Pro with audio file for transcription."""
    headers = get_auth_headers()

    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    mime_type = "audio/mp3" if audio_path.endswith(".mp3") else "audio/wav"

    url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{GEMINI_PRO_MODEL}:generateContent"

    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inlineData": {"mimeType": mime_type, "data": audio_b64}},
                {"text": prompt}
            ]
        }],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2048,
        }
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        raise Exception(f"Gemini Pro API error: {response.status_code} - {response.text}")

    result = response.json()
    return result["candidates"][0]["content"]["parts"][0]["text"].strip()


# =============================================================================
# IMAGE GENERATION (Nano Banana)
# =============================================================================

def generate_image(prompt: str, output_path: str) -> bool:
    """Generate image using Gemini 2.5 Flash Image (Nano Banana)."""
    headers = get_auth_headers()

    url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{IMAGE_MODEL}:generateContent"

    payload = {
        "contents": [{
            "role": "USER",
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {
                "aspectRatio": IMAGE_ASPECT_RATIO
            }
        }
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        print(f"  Image API error: {response.status_code} - {response.text[:300]}")
        return False

    result = response.json()

    try:
        candidates = result.get("candidates", [])
        if not candidates:
            print("  No candidates in response")
            return False

        parts = candidates[0].get("content", {}).get("parts", [])

        for part in parts:
            if "inlineData" in part:
                image_b64 = part["inlineData"].get("data", "")
                if image_b64:
                    image_bytes = base64.b64decode(image_b64)
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, "wb") as f:
                        f.write(image_bytes)
                    return True

        print("  No image data in response")
        return False

    except Exception as e:
        print(f"  Error parsing response: {e}")
        return False


# =============================================================================
# VIDEO GENERATION (VEO 3.1)
# =============================================================================

def generate_video_from_prompt(prompt: str, output_path: str, with_audio: bool = False, max_wait: int = 300) -> bool:
    """Generate video using VEO 3.1 fast (text-to-video, no image input)."""
    headers = get_auth_headers()

    model = VEO_MODEL

    url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{model}:predictLongRunning"

    payload = {
        "instances": [{
            "prompt": prompt
        }],
        "parameters": {
            "aspectRatio": VIDEO_ASPECT_RATIO,
            "durationSeconds": VIDEO_DURATION_SECONDS,
            "personGeneration": VIDEO_PERSON_GENERATION
        }
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        print(f"  VEO submit error: {response.status_code} - {response.text[:200]}")
        return False

    result = response.json()
    operation_name = result.get("name")

    if not operation_name:
        print("  No operation returned")
        return False

    print(f"  Operation submitted, polling...")
    return _poll_veo_operation(operation_name, output_path, model, max_wait)


def generate_video_from_image(image_path: str, prompt: str, output_path: str, with_audio: bool = True, max_wait: int = 300) -> bool:
    """Generate video using VEO 3.1 fast (image-to-video)."""
    headers = get_auth_headers()

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    mime_type = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"

    model = VEO_MODEL

    url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{model}:predictLongRunning"

    payload = {
        "instances": [{
            "prompt": prompt,
            "image": {
                "bytesBase64Encoded": image_b64,
                "mimeType": mime_type
            }
        }],
        "parameters": {
            "aspectRatio": VIDEO_ASPECT_RATIO,
            "durationSeconds": VIDEO_DURATION_SECONDS,
            "personGeneration": VIDEO_PERSON_GENERATION
        }
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        print(f"  VEO submit error: {response.status_code} - {response.text[:200]}")
        return False

    result = response.json()
    operation_name = result.get("name")

    if not operation_name:
        print("  No operation returned")
        return False

    print(f"  Operation submitted, polling...")
    return _poll_veo_operation(operation_name, output_path, model, max_wait)


def _poll_veo_operation(operation_name: str, output_path: str, model: str, max_wait: int) -> bool:
    """Poll VEO operation until complete."""
    fetch_url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{model}:fetchPredictOperation"

    start_time = time.time()
    while time.time() - start_time < max_wait:
        time.sleep(10)

        headers = get_auth_headers()
        poll_response = requests.post(
            fetch_url,
            headers=headers,
            json={"operationName": operation_name}
        )

        if poll_response.status_code != 200:
            continue

        poll_result = poll_response.json()

        if poll_result.get("done"):
            if "response" in poll_result:
                response_data = poll_result["response"]

                videos = response_data.get("videos", [])
                if videos:
                    video_b64 = videos[0].get("bytesBase64Encoded", "")
                    if video_b64:
                        video_bytes = base64.b64decode(video_b64)
                        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                        with open(output_path, "wb") as f:
                            f.write(video_bytes)
                        return True

                for sample in response_data.get("generatedSamples", []):
                    if "video" in sample:
                        video_b64 = sample["video"].get("bytesBase64Encoded", "")
                        if video_b64:
                            video_bytes = base64.b64decode(video_b64)
                            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                            with open(output_path, "wb") as f:
                                f.write(video_bytes)
                            return True

            if "error" in poll_result:
                print(f"  VEO error: {poll_result['error']}")
                return False

            print("  No video in response")
            return False

        elapsed = int(time.time() - start_time)
        print(f"  Still processing... ({elapsed}s)")

    print("  Timeout waiting for video")
    return False




# =============================================================================
# AUDIO/VIDEO UTILITIES
# =============================================================================

def get_audio_duration(audio_path: str) -> float:
    """Get duration of audio file in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 8.0  # Default fallback
    return 8.0


def extract_audio_from_video(video_path: str, output_audio: str) -> bool:
    """Extract audio from video file."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-q:a", "2",
        output_audio
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def mix_audios_and_add_to_video(video_path: str, human_audio: str, bg_audio: str, output_path: str) -> bool:
    """Mix human recital audio (80%) with background audio (20%) and add to video."""
    # Mix audio: human at 80%, background at 20%
    filter_complex = (
        f"[1:a]volume=0.8[human];"
        f"[2:a]volume=0.2[bg];"
        f"[human][bg]amix=inputs=2:duration=first[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", human_audio,
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
        print(f"    ffmpeg error: {result.stderr[-300:]}")
    return result.returncode == 0


def add_synced_subtitles(video_path: str, word_timestamps: list, output_path: str, text_color: str = None) -> tuple[bool, str, str]:
    """Add synced subtitles at 75% from top (karaoke-style).

    Returns: (success, color_hex, color_name) - whether it succeeded and which color was used
    """
    # Get random color if not specified
    if text_color is None:
        text_color, color_name = get_random_subtitle_color()
    else:
        # Find color name from hex
        color_name = "Custom"
        for c, n in SUBTITLE_COLORS:
            if c == text_color:
                color_name = n
                break

    # Split words into lines (assume 5 words per line for short shayaris)
    mid = len(word_timestamps) // 2
    line1_words = word_timestamps[:mid]
    line2_words = word_timestamps[mid:]

    if not line1_words or not line2_words:
        print("  Not enough words for lyrics sync")
        return False, text_color, color_name

    filters = []

    # Add dark strip background at 75% from top
    filters.append(f"drawbox=x=0:y=(ih*0.75)-130:w=iw:h=260:color=black@0.65:t=fill")

    y1 = "(h*0.75)-70"
    y2 = "(h*0.75)+20"

    line2_start = line2_words[0]["start"]

    # Line 1 words - progressive highlight
    for i, w in enumerate(line1_words):
        start = w["start"]
        prefix = " ".join([lw["word"] for lw in line1_words[:i+1]])
        next_start = line1_words[i+1]["start"] if i < len(line1_words)-1 else line2_start

        filters.append(
            f"drawtext=text='{prefix}':fontfile='{FONT_PATH}':fontsize={FONT_SIZE}:"
            f"fontcolor={text_color}:borderw={BORDER_WIDTH}:bordercolor={BORDER_COLOR}:"
            f"x=(w-text_w)/2:y={y1}:enable='between(t,{start},{next_start})'"
        )

    # Line 1 fully shown after all words
    full_line1 = " ".join([w["word"] for w in line1_words])
    filters.append(
        f"drawtext=text='{full_line1}':fontfile='{FONT_PATH}':fontsize={FONT_SIZE}:"
        f"fontcolor={text_color}:borderw={BORDER_WIDTH}:bordercolor={BORDER_COLOR}:"
        f"x=(w-text_w)/2:y={y1}:enable='gte(t,{line2_start})'"
    )

    # Line 2 words - progressive highlight
    for i, w in enumerate(line2_words):
        start = w["start"]
        prefix = " ".join([lw["word"] for lw in line2_words[:i+1]])
        next_start = line2_words[i+1]["start"] if i < len(line2_words)-1 else 8.0

        filters.append(
            f"drawtext=text='{prefix}':fontfile='{FONT_PATH}':fontsize={FONT_SIZE}:"
            f"fontcolor={text_color}:borderw={BORDER_WIDTH}:bordercolor={BORDER_COLOR}:"
            f"x=(w-text_w)/2:y={y2}:enable='between(t,{start},{next_start})'"
        )

    # Line 2 fully shown after last word
    full_line2 = " ".join([w["word"] for w in line2_words])
    last_word_start = line2_words[-1]["start"]
    filters.append(
        f"drawtext=text='{full_line2}':fontfile='{FONT_PATH}':fontsize={FONT_SIZE}:"
        f"fontcolor={text_color}:borderw={BORDER_WIDTH}:bordercolor={BORDER_COLOR}:"
        f"x=(w-text_w)/2:y={y2}:enable='gte(t,{last_word_start})'"
    )

    filter_str = ",".join(filters)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", filter_str,
        "-c:v", "libx264",
        "-c:a", "copy",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ffmpeg error: {result.stderr[-500:]}")
    return result.returncode == 0, text_color, color_name


# =============================================================================
# PROMPT GENERATORS
# =============================================================================

def generate_human_portrait_prompt(shayari: str, char_params: dict = None) -> tuple[str, dict]:
    """Generate prompt for human_recital_video.mp4 (character portrait).

    Returns: (prompt, char_params) - the prompt and the character parameters used
    """
    if char_params is None:
        char_params = get_random_recital_character()

    prompt = HUMAN_PORTRAIT_PROMPT_TEMPLATE.format(
        shayari=shayari,
        gender=char_params["gender"],
        age_range=char_params["age_range"],
        age_desc=char_params["age_desc"],
        voice_texture=char_params["voice_texture"],
        clothing=char_params["clothing"],
        setting=char_params["setting"],
    )
    result = call_gemini(prompt)
    return result, char_params


def generate_ambient_video_prompt(shayari: str, ambient_params: dict = None) -> tuple[str, dict]:
    """Generate prompt for ambient/scenic video.

    Returns: (prompt, ambient_params) - the prompt and the ambient parameters used
    """
    if ambient_params is None:
        ambient_params = get_random_ambient_params()

    prompt = AMBIENT_VIDEO_PROMPT_TEMPLATE.format(
        shayari=shayari,
        setting=ambient_params["setting"],
        hair=ambient_params["hair"],
        skin=ambient_params["skin"],
        features=ambient_params["features"],
        outfit=ambient_params["outfit"],
        cut_style=ambient_params["cut_style"],
        cut_desc=ambient_params["cut_desc"],
    )
    result = call_gemini(prompt)
    return result, ambient_params


def generate_human_video_prompt(shayari: str, char_params: dict = None) -> tuple[str, dict]:
    """Generate VEO prompt for human recital video.

    Returns: (prompt, char_params) - the prompt and the character parameters used
    """
    if char_params is None:
        char_params = get_random_recital_character()

    # Convert shayari for speech
    prose_text = shayari.replace(",", "…").replace("।", "।").replace("!", "…")
    if not prose_text.endswith("।") and not prose_text.endswith("…"):
        prose_text += "…"

    prompt = VIDEO_TIMELINE_TEMPLATE.format(shayari=prose_text)
    timeline = call_gemini(prompt)

    # Clean up
    if timeline.startswith("```"):
        lines = timeline.split("\n")
        timeline = "\n".join(lines[1:-1]).strip()

    # Build intro with character params
    intro = HUMAN_VIDEO_PROMPT_INTRO_TEMPLATE.format(
        gender=char_params["gender"],
        age_range=char_params["age_range"],
        age_desc=char_params["age_desc"],
        voice_texture=char_params["voice_texture"],
    )

    return f"{intro}\n{timeline}\n{HUMAN_VIDEO_PROMPT_OUTRO}", char_params


def get_word_timestamps(audio_path: str) -> list:
    """Get word-level timestamps from audio using Gemini 2.5 Pro."""
    response = call_gemini_with_audio(audio_path, AUDIO_TRANSCRIPTION_PROMPT)

    # Extract JSON from response
    response = response.strip()
    if response.startswith("```json"):
        response = response[7:]
    if response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]

    try:
        timestamps = json.loads(response.strip())
        return timestamps
    except json.JSONDecodeError as e:
        print(f"  Failed to parse timestamps: {e}")
        print(f"  Response was: {response[:200]}")
        return []




# =============================================================================
# MAIN PIPELINE
# =============================================================================

def load_data(input_path: str) -> tuple[list, Path]:
    """Load input JSON and determine output directory based on JSON filename."""
    input_file = Path(input_path)
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Use JSON filename (without extension) as output subfolder
    json_name = input_file.stem
    output_dir = OUTPUTS_DIR / json_name
    output_dir.mkdir(parents=True, exist_ok=True)

    return data, output_dir


def save_data(data: list, input_path: str, output_dir: Path = None):
    """Save updated data back to input file and optionally to output folder."""
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Also save to output folder for reference
    if output_dir:
        output_json_path = output_dir / "generation_config.json"
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def run_pipeline(
    input_path: str,
    item_index: int = None,
    force: bool = False
):
    """Run the video generation pipeline."""

    data, base_output_dir = load_data(input_path)

    if item_index is not None:
        if item_index >= len(data):
            print(f"Error: Index {item_index} out of range (max {len(data)-1})")
            return
        items_to_process = [(item_index, data[item_index])]
    else:
        items_to_process = list(enumerate(data))

    total = len(items_to_process)
    print(f"Processing {total} items from {input_path}")
    if force:
        print("Force mode: regenerating existing outputs")
    print()

    for idx, (i, item) in enumerate(items_to_process, 1):
        item_id = item.get("id", f"shayari_{i:04d}")
        shayari = item.get("shayari", "")

        if not shayari:
            print(f"[{idx}/{total}] {item_id}: Skipping (no shayari)")
            continue

        print(f"[{idx}/{total}] {item_id}")
        print(f"  Shayari: {shayari[:60]}...")

        # Setup output directories
        output_dir = base_output_dir / item_id
        intermediate_dir = output_dir / "intermediate"
        output_dir.mkdir(parents=True, exist_ok=True)
        intermediate_dir.mkdir(parents=True, exist_ok=True)

        # Initialize format paths in item
        if "formats" not in item:
            item["formats"] = {}
        formats = item["formats"]

        # Intermediate paths
        human_portrait_path = str(intermediate_dir / "human_portrait.jpeg")
        human_recital_raw = str(intermediate_dir / "human_recital_raw.mp4")
        human_audio_path = str(intermediate_dir / "human_audio.mp3")
        ambient_video_path = str(intermediate_dir / "ambient_video.mp4")
        word_timestamps_path = str(intermediate_dir / "word_timestamps.json")

        # Output path
        ambient_recital_path = str(output_dir / "ambient_video.mp4")

        # =====================================================================
        # STEP 1: Generate human_recital video with audio (veo3.1-fast)
        # =====================================================================
        if force or not Path(human_recital_raw).exists():
            print("  → Generating human_recital_video.mp4 (veo3.1-fast with audio)...")
            try:
                # Get or generate character params for consistency
                char_params = item.get("recital_character_params")
                if force or not char_params:
                    char_params = get_random_recital_character()
                    item["recital_character_params"] = char_params
                    print(f"    → Character: {char_params['gender']}, {char_params['age_range']}, {char_params['voice_texture'][:30]}...")
                    save_data(data, input_path, base_output_dir)

                # Generate human video prompt (timeline for speaking)
                if force or not item.get("human_video_prompt"):
                    print("    → Generating human video prompt...")
                    item["human_video_prompt"], _ = generate_human_video_prompt(shayari, char_params)
                    save_data(data, input_path, base_output_dir)
                    time.sleep(GEMINI_DELAY)

                # Generate portrait image prompt (character for video)
                if force or not item.get("human_portrait_prompt"):
                    print("    → Generating character portrait prompt...")
                    item["human_portrait_prompt"], _ = generate_human_portrait_prompt(shayari, char_params)
                    save_data(data, input_path, base_output_dir)
                    time.sleep(GEMINI_DELAY)

                # Generate character portrait image
                if force or not Path(human_portrait_path).exists():
                    print("    → Generating character portrait image...")
                    generate_image(item["human_portrait_prompt"], human_portrait_path)

                if Path(human_portrait_path).exists():
                    print(f"    → Generating human recital video (veo3.1-fast with audio)...")
                    print(f"    → Prompt: {item['human_video_prompt'][:80]}...")

                    if generate_video_from_image(human_portrait_path, item["human_video_prompt"],
                                                 human_recital_raw, with_audio=True):
                        print(f"    ✓ Human recital raw video generated")

                        # Extract audio from Veo video
                        print("    → Extracting voice audio from Veo video...")
                        if extract_audio_from_video(human_recital_raw, human_audio_path):
                            print(f"    ✓ Voice audio extracted")
                        else:
                            print("    ⚠ Audio extraction failed")
                    else:
                        print("  ✗ Human recital video generation failed")
                else:
                    print("  ⏭ Character portrait not available, skipping human recital")
            except Exception as e:
                print(f"  ✗ human_recital error: {e}")
        else:
            print("  ⏭ human_recital_raw.mp4 exists, extracting audio if needed...")
            # Extract audio if not already done
            if not Path(human_audio_path).exists():
                print("    → Extracting voice audio from existing Veo video...")
                if extract_audio_from_video(human_recital_raw, human_audio_path):
                    print(f"    ✓ Voice audio extracted")

        # =====================================================================
        # STEP 2: Generate Ambient Video (veo3.1 without audio)
        # =====================================================================
        if force or not Path(ambient_video_path).exists():
            print("  → Generating ambient video (veo3.1 without audio)...")
            try:
                # Get or generate ambient params for consistency
                ambient_params = item.get("ambient_video_params")
                if force or not ambient_params:
                    ambient_params = get_random_ambient_params()
                    item["ambient_video_params"] = ambient_params
                    print(f"    → Setting: {ambient_params['setting'][:40]}...")
                    print(f"    → Woman: {ambient_params['hair']}, {ambient_params['outfit'][:30]}...")
                    print(f"    → Cut style: {ambient_params['cut_style']}")
                    save_data(data, input_path, base_output_dir)

                if force or not item.get("ambient_video_prompt"):
                    print("    → Generating ambient video prompt...")
                    item["ambient_video_prompt"], _ = generate_ambient_video_prompt(shayari, ambient_params)
                    save_data(data, input_path, base_output_dir)
                    time.sleep(GEMINI_DELAY)

                print(f"    → Prompt: {item['ambient_video_prompt'][:80]}...")
                if generate_video_from_prompt(item["ambient_video_prompt"], ambient_video_path, with_audio=False):
                    print(f"    ✓ Ambient video generated (without audio)")
                else:
                    print("    ✗ Ambient video generation failed")
            except Exception as e:
                print(f"    ✗ Ambient video error: {e}")

        # =====================================================================
        # STEP 3: Mix audio and create final videos
        # =====================================================================
        # Get random background audio (shared for both outputs)
        bg_audio = None
        mixed_audio_path = str(intermediate_dir / "mixed_audio.mp3")
        word_timestamps = []

        if Path(human_audio_path).exists():
            # Get word timestamps (needed for both videos)
            if Path(word_timestamps_path).exists():
                with open(word_timestamps_path, "r") as f:
                    word_timestamps = json.load(f)
            else:
                print("    → Getting word timestamps for synced subtitles...")
                word_timestamps = get_word_timestamps(human_audio_path)
                if word_timestamps:
                    with open(word_timestamps_path, "w") as f:
                        json.dump(word_timestamps, f, ensure_ascii=False, indent=2)
                    print(f"    ✓ Got {len(word_timestamps)} word timestamps")

            # Get background audio
            bg_audio = get_random_audio_from_library()

        # ---------------------------------------------------------------------
        # OUTPUT 1: ambient_video.mp4 (ambient video + mixed audio + subtitles)
        # ---------------------------------------------------------------------
        if Path(ambient_video_path).exists() and Path(human_audio_path).exists():
            if force or not formats.get("ambient_video"):
                print("  → Creating ambient_video.mp4...")

                if bg_audio:
                    temp_video = str(intermediate_dir / "ambient_with_mixed_audio.mp4")
                    print("    → Mixing audio (80% human recital + 20% background music)...")

                    if mix_audios_and_add_to_video(ambient_video_path, human_audio_path,
                                                    bg_audio, temp_video):
                        print("    ✓ Audio mixed successfully")

                        if word_timestamps:
                            print("    → Adding synced subtitles at 75%...")
                            success, color_hex, color_name = add_synced_subtitles(temp_video, word_timestamps, ambient_recital_path)
                            if success:
                                formats["ambient_video"] = ambient_recital_path
                                item["ambient_subtitle_color"] = {"hex": color_hex, "name": color_name}
                                print(f"  ✓ ambient_video.mp4 saved with {color_name} subtitles")
                                save_data(data, input_path, base_output_dir)
                            else:
                                import shutil
                                shutil.copy(temp_video, ambient_recital_path)
                                formats["ambient_video"] = ambient_recital_path
                                print(f"  ✓ ambient_video.mp4 saved (subtitle addition failed)")
                                save_data(data, input_path, base_output_dir)
                        else:
                            import shutil
                            shutil.copy(temp_video, ambient_recital_path)
                            formats["ambient_video"] = ambient_recital_path
                            print(f"  ✓ ambient_video.mp4 saved (no subtitles)")
                            save_data(data, input_path, base_output_dir)

                        Path(temp_video).unlink(missing_ok=True)
                    else:
                        print("  ✗ Audio mixing failed for ambient_video")
                else:
                    print("  ✗ No background audio available")
            else:
                print("  ⏭ ambient_video.mp4 exists, skipping")
        else:
            print("  ⏭ Missing ambient_video or human_audio, skipping ambient_video.mp4")

        # ---------------------------------------------------------------------
        # OUTPUT 2: recital_video.mp4 (human recital video + mixed audio + subtitles)
        # ---------------------------------------------------------------------
        recital_output_path = str(output_dir / "recital_video.mp4")

        if Path(human_recital_raw).exists() and Path(human_audio_path).exists():
            if force or not formats.get("recital_video"):
                print("  → Creating recital_video.mp4...")

                if bg_audio:
                    temp_video = str(intermediate_dir / "recital_with_mixed_audio.mp4")
                    print("    → Mixing audio (80% human recital + 20% background music)...")

                    if mix_audios_and_add_to_video(human_recital_raw, human_audio_path,
                                                    bg_audio, temp_video):
                        print("    ✓ Audio mixed successfully")

                        if word_timestamps:
                            # Use a DIFFERENT subtitle color for recital video
                            print("    → Adding synced subtitles at 75% (different color)...")
                            success, color_hex, color_name = add_synced_subtitles(temp_video, word_timestamps, recital_output_path)
                            if success:
                                formats["recital_video"] = recital_output_path
                                item["recital_subtitle_color"] = {"hex": color_hex, "name": color_name}
                                print(f"  ✓ recital_video.mp4 saved with {color_name} subtitles")
                                save_data(data, input_path, base_output_dir)
                            else:
                                import shutil
                                shutil.copy(temp_video, recital_output_path)
                                formats["recital_video"] = recital_output_path
                                print(f"  ✓ recital_video.mp4 saved (subtitle addition failed)")
                                save_data(data, input_path, base_output_dir)
                        else:
                            import shutil
                            shutil.copy(temp_video, recital_output_path)
                            formats["recital_video"] = recital_output_path
                            print(f"  ✓ recital_video.mp4 saved (no subtitles)")
                            save_data(data, input_path, base_output_dir)

                        Path(temp_video).unlink(missing_ok=True)
                    else:
                        print("  ✗ Audio mixing failed for recital_video")
                else:
                    print("  ✗ No background audio available")
            else:
                print("  ⏭ recital_video.mp4 exists, skipping")
        else:
            print("  ⏭ Missing human_recital_raw or human_audio, skipping recital_video.mp4")

        print()

    print("Done!")


def main():
    parser = argparse.ArgumentParser(description="Video Generation Pipeline - Ambient Video Focus")

    parser.add_argument("--input", type=str, required=True, help="Input JSON file")
    parser.add_argument("--index", type=int, help="Process single item by index")
    parser.add_argument("--force", action="store_true", help="Regenerate even if output exists")

    args = parser.parse_args()

    run_pipeline(
        args.input,
        item_index=args.index,
        force=args.force
    )


if __name__ == "__main__":
    main()