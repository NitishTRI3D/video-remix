# Video Generation Pipeline

Generate ambient videos with human-recital audio and synced subtitles for Hindi shayari.

## Features

- Human recital video generation using Veo 3.1-fast (with audio)
- Ambient video generation using Veo 3.1 (without audio)
- Audio mixing: 80% human recital + 20% background music from library
- Centered synced subtitles
- Standalone project with virtual environment

## Setup

1. Make sure you have Python 3.8+ installed
2. Run the setup script:
   ```bash
   ./setup.sh
   ```

3. Activate the virtual environment:
   ```bash
   source venv/bin/activate
   ```

## Usage

Process all items in a JSON file:
```bash
python video_gen.py --input inputs/test.json
```

Process a specific item by index:
```bash
python video_gen.py --input inputs/test.json --index 0
```

Force regenerate (overwrite existing outputs):
```bash
python video_gen.py --input inputs/test.json --force
```

## Input Format

Create a JSON file in the `inputs/` folder with this format:
```json
[
  {
    "id": "shayari_001",
    "shayari": "Your Hindi shayari text here"
  }
]
```

## Audio Library

Add background music files (MP3/WAV) to `inputs/audio_library/`. The pipeline will randomly select one for each video.

## Output

Videos are saved in `outputs/{json_filename}/{item_id}/ambient_video.mp4`


## Requirements

- Google Cloud service account with access to:
  - Vertex AI (Gemini, Veo, Imagen)
- FFmpeg installed on your system