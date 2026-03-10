"""
Podcast Transcription Script
=============================
Transcribes all audio files in style_corpus/samples/audio/ using OpenAI Whisper
and saves transcripts to style_corpus/samples/.

Usage:
    python transcribe_podcasts.py

Requires:
    pip install openai
    Set OPENAI_API_KEY environment variable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from openai import OpenAI

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
AUDIO_DIR = SCRIPT_DIR / "style_corpus" / "samples" / "audio"
OUTPUT_DIR = SCRIPT_DIR / "style_corpus" / "samples"

SUPPORTED_FORMATS = {".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".flac", ".webm", ".mpeg", ".mpga"}
MAX_FILE_SIZE_MB = 25


def get_audio_files() -> list[Path]:
    if not AUDIO_DIR.exists():
        print(f"ERROR: Audio directory not found: {AUDIO_DIR}")
        print(f"Download your podcast episodes there first.")
        sys.exit(1)

    files = [f for f in AUDIO_DIR.iterdir() if f.suffix.lower() in SUPPORTED_FORMATS]
    if not files:
        print(f"No audio files found in {AUDIO_DIR}")
        print(f"Supported formats: {', '.join(sorted(SUPPORTED_FORMATS))}")
        sys.exit(1)

    return sorted(files)


def split_large_file(filepath: Path) -> list[Path]:
    """If file exceeds Whisper's 25MB limit, split it using pydub."""
    size_mb = filepath.stat().st_size / (1024 * 1024)
    if size_mb <= MAX_FILE_SIZE_MB:
        return [filepath]

    print(f"  File is {size_mb:.1f}MB (>{MAX_FILE_SIZE_MB}MB limit). Splitting...")
    try:
        from pydub import AudioSegment
    except ImportError:
        print("  ERROR: pip install pydub (and install ffmpeg) for large file splitting")
        print(f"  Skipping {filepath.name}")
        return []

    audio = AudioSegment.from_file(str(filepath))
    chunk_ms = 10 * 60 * 1000  # 10-minute chunks
    chunks = []

    for i, start in enumerate(range(0, len(audio), chunk_ms)):
        chunk = audio[start:start + chunk_ms]
        chunk_path = filepath.parent / f"{filepath.stem}_part{i+1}.mp3"
        chunk.export(str(chunk_path), format="mp3", bitrate="64k")
        chunks.append(chunk_path)
        print(f"  Created chunk: {chunk_path.name}")

    return chunks


def transcribe_file(client: OpenAI, filepath: Path) -> str:
    """Transcribe a single audio file using Whisper."""
    with open(filepath, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text",
        )
    return response


def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("ERROR: Set the OPENAI_API_KEY environment variable.")
        print('  In PowerShell: $env:OPENAI_API_KEY = "sk-..."')
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    audio_files = get_audio_files()

    print(f"=== Podcast Transcription ===")
    print(f"Found {len(audio_files)} audio file(s) in {AUDIO_DIR}")
    print(f"Transcripts will be saved to {OUTPUT_DIR}")
    print()

    for i, filepath in enumerate(audio_files, 1):
        size_mb = filepath.stat().st_size / (1024 * 1024)
        print(f"[{i}/{len(audio_files)}] Transcribing: {filepath.name} ({size_mb:.1f}MB)")

        output_path = OUTPUT_DIR / f"podcast_{filepath.stem}.txt"
        if output_path.exists():
            print(f"  Already transcribed, skipping. Delete {output_path.name} to redo.")
            continue

        chunks = split_large_file(filepath)
        if not chunks:
            continue

        full_transcript = []
        for j, chunk_path in enumerate(chunks):
            if len(chunks) > 1:
                print(f"  Transcribing part {j+1}/{len(chunks)}...")
            transcript = transcribe_file(client, chunk_path)
            full_transcript.append(transcript)

            if chunk_path != filepath:
                chunk_path.unlink()

        combined = "\n\n".join(full_transcript)
        output_path.write_text(combined, encoding="utf-8")
        word_count = len(combined.split())
        print(f"  Done: {output_path.name} ({word_count:,} words)")

    print()
    print("=== All transcriptions complete ===")
    transcript_files = list(OUTPUT_DIR.glob("podcast_*.txt"))
    total_words = sum(len(f.read_text(encoding="utf-8").split()) for f in transcript_files)
    print(f"Total transcripts: {len(transcript_files)}")
    print(f"Total words: {total_words:,}")
    print(f"Location: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
