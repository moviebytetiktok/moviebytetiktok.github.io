import os
import subprocess
import uuid
import json
import math
import tempfile
from dataclasses import dataclass
from typing import List, Tuple, Optional

# Whisper (local) for transcription
import whisper

# Simple NLP bits
import re

FFMPEG = os.environ.get("FFMPEG_PATH", "ffmpeg")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")

# --- Data types ---
@dataclass
class ClipWindow:
    start: float
    end: float
    score: float


def run(cmd: list):
    # Helper to run shell commands robustly
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{proc.stderr}")
    return proc


# ---------- Ingest ----------
def ingest_url_to_file(url: str, dest_dir: str) -> str:
    """
    Uses yt-dlp (must be installed) to download the best mp4/mp3 to dest_dir.
    """
    os.makedirs(dest_dir, exist_ok=True)
    template = os.path.join(dest_dir, "%(title).80s-%(id)s.%(ext)s")
    cmd = ["yt-dlp", "-f", "mp4/bestaudio/best", "-o", template, url]
    run(cmd)
    # Find the newest file in dest_dir
    latest = max((os.path.join(dest_dir, f) for f in os.listdir(dest_dir)), key=os.path.getctime)
    return latest


# ---------- Transcription ----------
def transcribe_to_srt(input_path: str, srt_out: str, language: Optional[str] = None):
    """
    Transcribe audio to SRT using OpenAI Whisper (local).
    """
    model = whisper.load_model(WHISPER_MODEL)
    result = model.transcribe(input_path, language=language, verbose=False)
    # Build SRT
    lines = []
    for i, seg in enumerate(result["segments"]):
        idx = i + 1
        start = _sec_to_srt_time(seg["start"])
        end   = _sec_to_srt_time(seg["end"])
        text  = seg["text"].strip()
        lines.append(f"{idx}\n{start} --> {end}\n{text}\n")
    with open(srt_out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _sec_to_srt_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------- Highlighting ----------
KEYWORDS = [
    "tip", "secret", "mistake", "common", "best", "worst", "always", "never",
    "how to", "here's", "watch this", "listen", "idea", "hack", "strategy",
    "story", "example", "because", "why", "myth", "truth"
]


def find_highlights(src_path: str, srt_path: str, target_len: int = 15, max_clips: int = 6) -> List[ClipWindow]:
    """
    Heuristic: score SRT sentences, merge into ~target_len windows, pick top-N.
    """
    entries = _parse_srt(srt_path)
    if not entries:
        # fallback: chop the raw video into 15s chunks
        duration = _probe_duration(src_path)
        windows = []
        t = 0.0
        while t < duration and len(windows) < max_clips:
            windows.append(ClipWindow(start=t, end=min(t+target_len, duration), score=0.1))
            t += target_len
        return windows

    # Score sentences
    for e in entries:
        text = e["text"].lower()
        score = 0.0
        # keyword bonus
        for kw in KEYWORDS:
            if kw in text:
                score += 1.0
        # speech density (short and punchy wins)
        duration = e["end"] - e["start"]
        words = max(1, len(text.split()))
        wps = words / max(0.5, duration)
        score += min(wps / 3.0, 1.0)  # cap
        e["score"] = score

    # Slide a window to accumulate ~target_len around high-score centers
    windows: List[ClipWindow] = []
    for i, e in enumerate(entries):
        # seed only if above tiny threshold
        if e["score"] < 0.5:
            continue
        center = (e["start"] + e["end"]) / 2
        start = max(0.0, center - target_len / 2)
        end = start + target_len
        # Clamp to full duration
        vid_dur = _probe_duration(src_path)
        if end > vid_dur:
            end = vid_dur
            start = max(0.0, end - target_len)
        # aggregate score of sentences overlapping window
        win_score = 0.0
        for s in entries:
            if s["end"] < start or s["start"] > end:
                continue
            win_score += s["score"]
        windows.append(ClipWindow(start=start, end=end, score=win_score))

    # Fallback if nothing scored
    if not windows:
        duration = _probe_duration(src_path)
        t = 0.0
        while t < duration and len(windows) < max_clips:
            windows.append(ClipWindow(start=t, end=min(t+target_len, duration), score=0.1))
            t += target_len

    # Deduplicate overlapping windows by greedy pick
    windows.sort(key=lambda w: w.score, reverse=True)
    picked: List[ClipWindow] = []
    for w in windows:
        if len(picked) >= max_clips:
            break
        if all(not _overlap(w, p, frac=0.5) for p in picked):
            picked.append(w)
    return picked


def _overlap(a: ClipWindow, b: ClipWindow, frac=0.5) -> bool:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    return inter >= frac * min(a.end - a.start, b.end - b.start)


def _parse_srt(path: str):
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        block = []
        for line in f:
            line = line.rstrip("\n")
            if line.strip() == "":
                if block:
                    entries.append(_parse_block(block))
                    block = []
            else:
                block.append(line)
        if block:
            entries.append(_parse_block(block))
    # drop Nones
    return [e for e in entries if e]


def _parse_block(block: List[str]):
    # Expect:
    # idx
    # 00:00:01,000 --> 00:00:03,000
    # text...
    if len(block) < 3:
        return None
    time_line = block[1]
    m = re.match(r".*?(\d+:\d+:\d+,\d+)\s+-->\s+(\d+:\d+:\d+,\d+)", time_line)
    if not m:
        return None
    start = _srt_time_to_sec(m.group(1))
    end = _srt_time_to_sec(m.group(2))
    text = " ".join(block[2:]).strip()
    return {"start": start, "end": end, "text": text}


def _srt_time_to_sec(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0


def _probe_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return 0.0
    try:
        return float(proc.stdout.strip())
    except:
        return 0.0


# ---------- Rendering ----------
ASS_STYLES = {
    "default": {
        "Fontname": "Arial Black",
        "Fontsize": "48",
        "PrimaryColour": "&H00FFFFFF",
        "OutlineColour": "&H00000000",
        "BackColour": "&H80000000",
        "Bold": "1",
        "Italic": "0",
        "BorderStyle": "3",
        "Outline": "3",
        "Shadow": "0",
        "Alignment": "2",  # bottom-center
        "MarginL": "80",
        "MarginR": "80",
        "MarginV": "60",
        "Encoding": "1"
    }
}

def _ass_header(style_name: str):
    s = ASS_STYLES.get(style_name, ASS_STYLES["default"])
    head = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
    styles = (
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{s['Fontname']},{s['Fontsize']},{s['PrimaryColour']},&H000000FF,{s['OutlineColour']},{s['BackColour']},"
        f"{s['Bold']},{s['Italic']},0,0,100,100,0,0,{s['BorderStyle']},{s['Outline']},{s['Shadow']},"
        f"{s['Alignment']},{s['MarginL']},{s['MarginR']},{s['MarginV']},{s['Encoding']}\n\n"
    )
    events = "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    return head + styles + events


def _srt_to_ass(srt_path: str, ass_path: str, style_name: str):
    def to_ass_time(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        cs = int((t - int(t)) * 100)  # centiseconds
        return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"

    entries = _parse_srt(srt_path)
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(_ass_header(style_name))
        for e in entries:
            start = to_ass_time(e["start"])
            end = to_ass_time(e["end"])
            # Basic emphasis effect: \fad and \kf could be added here if desired
            text = e["text"].replace("\n", " ").replace("{", r"\{").replace("}", r"\}")
            f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")


def _aspect_filter(aspect: str) -> Tuple[int, int, str]:
    if aspect == "9:16":
        return 1080, 1920, "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    if aspect == "1:1":
        return 1080, 1080, "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"
    # default 16:9
    return 1920, 1080, "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"


def render_clips_with_captions(
    src_path: str,
    srt_path: str,
    clips: List["ClipWindow"],
    out_dir: str,
    aspect: str = "9:16",
    style: str = "default"
):
    ass_path = os.path.join(out_dir, "captions.ass")
    os.makedirs(out_dir, exist_ok=True)
    _srt_to_ass(srt_path, ass_path, style)

    w, h, vf_aspect = _aspect_filter(aspect)
    manifest = []

    for idx, clip in enumerate(clips, start=1):
        out_name = f"clip_{idx:02d}.mp4"
        out_path = os.path.join(out_dir, out_name)

        # Create the clip with trim, crop/scale, and burn-in subtitles
        # Note: Using -ss before -i for faster seeking; adjust if accuracy issues.
        cmd = [
            FFMPEG,
            "-y",
            "-ss", str(max(0.0, clip.start)),
            "-i", src_path,
            "-t", f"{max(0.1, clip.end - clip.start):.3f}",
            "-vf", f"{vf_aspect},subtitles='{ass_path}':force_style='Alignment=2'",
            "-r", "30",
            "-pix_fmt", "yuv420p",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "21",
            "-c:a", "aac",
            "-b:a", "160k",
            out_path
        ]
        run(cmd)

        manifest.append({
            "file": out_name,
            "start": round(clip.start, 3),
            "end": round(clip.end, 3),
            "score": round(clip.score, 3),
            "width": w,
            "height": h
        })

    return manifest
