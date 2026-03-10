"""
The Voice — Audio Voice Clone Service
======================================
Converts text to speech using Woody's cloned voice via ElevenLabs API.

Usage:
    # One-off text-to-speech
    python voice_service.py --text "Today's market wrap..."
    python voice_service.py --file daily_wrap_2026-03-06.md

    # Run as local HTTP service (for other agents to call)
    python voice_service.py --serve

    # Clone setup (upload audio samples to ElevenLabs)
    python voice_service.py --setup

Requires:
    pip install elevenlabs pyyaml flask
    Set ELEVENLABS_API_KEY environment variable.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        print("ERROR: Set the ELEVENLABS_API_KEY environment variable.")
        print("  Get your key at: https://elevenlabs.io/app/settings/api-keys")
        sys.exit(1)
    return key


def synthesize_speech(text: str, config: dict, output_path: Path | None = None) -> Path:
    """Convert text to speech using ElevenLabs API."""
    from elevenlabs import ElevenLabs

    api_key = get_api_key()
    client = ElevenLabs(api_key=api_key)

    el_config = config["elevenlabs"]
    voice_id = el_config["voice_id"]

    if not voice_id:
        print("ERROR: No voice_id configured. Run --setup first to create your voice clone.")
        print("  Or set voice_id in config.yaml after creating it at https://elevenlabs.io")
        sys.exit(1)

    audio_generator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=el_config["model_id"],
        voice_settings={
            "stability": el_config["stability"],
            "similarity_boost": el_config["similarity_boost"],
            "style": el_config.get("style", 0.5),
            "use_speaker_boost": el_config.get("use_speaker_boost", True),
        },
    )

    audio_bytes = b"".join(audio_generator)

    if output_path is None:
        output_dir = SCRIPT_DIR / config["output"]["directory"]
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = config["output"]["default_format"]
        output_path = output_dir / f"voice_{timestamp}.{ext}"

    output_path.write_bytes(audio_bytes)
    print(f"Audio saved: {output_path} ({len(audio_bytes) / 1024:.1f} KB)")
    return output_path


def setup_voice_clone(config: dict) -> None:
    """Guide through ElevenLabs voice clone setup."""
    from elevenlabs import ElevenLabs

    api_key = get_api_key()
    client = ElevenLabs(api_key=api_key)

    samples_dir = SCRIPT_DIR / config["training"]["samples_directory"]

    print("=== Voice Clone Setup ===")
    print()
    print("Step 1: Collect audio samples")
    print(f"  Place audio files in: {samples_dir}")
    print(f"  Minimum: {config['training']['min_minutes']} minutes")
    print(f"  Target:  {config['training']['target_minutes']} minutes")
    print(f"  Source:  Courage Over Convention podcast episodes")
    print(f"  Dropbox: https://www.dropbox.com/t/riyUu6X4RvoCEGsE")
    print()

    audio_files = []
    if samples_dir.exists():
        for ext in ["*.mp3", "*.wav", "*.m4a", "*.ogg", "*.flac"]:
            audio_files.extend(samples_dir.glob(ext))

    if not audio_files:
        print(f"  No audio files found in {samples_dir}")
        print("  Download your podcast episodes and place them there.")
        print()
        print("Step 2: Once you have audio samples, run this command again.")
        print("  The script will upload them to ElevenLabs and create your voice clone.")
        return

    print(f"  Found {len(audio_files)} audio file(s):")
    for f in audio_files:
        print(f"    - {f.name}")
    print()

    confirm = input("Upload these to ElevenLabs and create voice clone? (y/N): ")
    if confirm.lower() != "y":
        print("Aborted.")
        return

    print("Creating voice clone on ElevenLabs...")
    print("(For Professional Voice Cloning, use the ElevenLabs web UI instead)")
    print()

    file_handles = [open(f, "rb") for f in audio_files]
    try:
        voice = client.voices.add(
            name="Woody Wiegmann",
            description="Woody Wiegmann - Courage Over Convention podcast host, Potomac Fund Management analyst",
            files=file_handles,
        )
        print(f"Voice clone created successfully!")
        print(f"  Voice ID: {voice.voice_id}")
        print(f"  Name: {voice.name}")
        print()
        print(f"Add this voice_id to config.yaml:")
        print(f'  voice_id: "{voice.voice_id}"')
    finally:
        for fh in file_handles:
            fh.close()


def run_server(config: dict) -> None:
    """Run as a local HTTP service for other agents to call."""
    from flask import Flask, request, jsonify, send_file

    app = Flask(__name__)

    @app.route("/synthesize", methods=["POST"])
    def synthesize():
        data = request.json
        text = data.get("text", "")
        if not text:
            return jsonify({"error": "No text provided"}), 400

        output_format = data.get("output_format", config["output"]["default_format"])
        output_dir = SCRIPT_DIR / config["output"]["directory"]
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"voice_{timestamp}.{output_format}"

        synthesize_speech(text, config, output_path)
        return send_file(str(output_path), mimetype=f"audio/{output_format}")

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "voice_id": config["elevenlabs"]["voice_id"]})

    server_config = config["server"]
    print(f"Starting Voice Clone service on {server_config['host']}:{server_config['port']}")
    app.run(host=server_config["host"], port=server_config["port"])


def main() -> None:
    parser = argparse.ArgumentParser(description="The Voice — Audio Voice Clone Service")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Text to convert to speech")
    group.add_argument("--file", help="File containing text to convert")
    group.add_argument("--serve", action="store_true", help="Run as HTTP service")
    group.add_argument("--setup", action="store_true", help="Set up voice clone on ElevenLabs")
    parser.add_argument("--output", "-o", help="Output file path")
    args = parser.parse_args()

    config = load_config()

    if args.setup:
        setup_voice_clone(config)
        return

    if args.serve:
        run_server(config)
        return

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    else:
        text = args.text

    output_path = Path(args.output) if args.output else None
    synthesize_speech(text, config, output_path)


if __name__ == "__main__":
    main()
