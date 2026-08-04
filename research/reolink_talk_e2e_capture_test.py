#!/usr/bin/env python3
"""
End-to-end validation for Reolink two-way audio:

1) Capture RTSP audio from the camera mic for N seconds (baseline).
2) Capture RTSP audio again while sending a loud 1kHz sine over Baichuan talk.

If the camera speaker actually plays audio, the camera mic often picks it up,
so the 1kHz tone will show up in the second capture.

Outputs:
  media/reolink_talk_baseline.wav
  media/reolink_talk_during_talk.wav

This script relies on:
  - ffmpeg (for RTSP capture)
  - scripts/reolink_talk_debug.py (for sending talk)
  - .storage/core.config_entries(.bak_*) containing the official Reolink creds
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_core_config_entries() -> dict:
    storage_dir = ROOT / ".storage"
    candidates: list[Path] = []
    for pat in ("core.config_entries", "core.config_entries.bak_*", "core.config_entries.*"):
        candidates.extend(sorted(storage_dir.glob(pat)))
    seen: set[Path] = set()
    for p in candidates:
        if p in seen or not p.is_file():
            continue
        seen.add(p)
        try:
            raw = p.read_bytes().rstrip(b"\x00")
            obj = json.loads(raw.decode("utf-8", "strict"))
        except Exception:
            continue
        if obj.get("key") == "core.config_entries":
            return obj
    raise FileNotFoundError("No valid .storage/core.config_entries JSON found (key=core.config_entries)")


def _get_reolink_entry(title: str) -> dict:
    obj = _load_core_config_entries()
    for e in obj.get("data", {}).get("entries", []):
        if e.get("domain") != "reolink":
            continue
        if (e.get("title") or "").lower() == title.lower():
            d = e.get("data", {})
            return {
                "title": e.get("title"),
                "host": d.get("host"),
                "username": d.get("username"),
                "password": d.get("password"),
            }
    raise KeyError(f"Reolink entry not found for title={title!r}")


def _capture_rtsp_wav(*, url: str, seconds: float, out_path: Path, sample_rate: int = 16000) -> None:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        url,
        "-t",
        str(float(seconds)),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(int(sample_rate)),
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "ignore")[:800])


def _goertzel_power_1khz(wav_path: Path, *, freq_hz: float = 1000.0) -> tuple[float, float]:
    # Return (rms, power_at_freq). Works on mono pcm_s16le wavs.
    import wave

    with wave.open(str(wav_path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("expected mono 16-bit WAV")
        sr = float(w.getframerate())
        frames = w.readframes(w.getnframes())
    samples = struct.unpack("<" + ("h" * (len(frames) // 2)), frames) if frames else ()
    if not samples:
        return (0.0, 0.0)

    rms = math.sqrt(sum((s / 32768.0) ** 2 for s in samples) / len(samples))

    # Goertzel single-frequency detector.
    n = len(samples)
    k = int(0.5 + (n * freq_hz) / sr)
    omega = (2.0 * math.pi * k) / n
    coeff = 2.0 * math.cos(omega)
    s_prev = 0.0
    s_prev2 = 0.0
    for x in samples:
        s = float(x) + coeff * s_prev - s_prev2
        s_prev2 = s_prev
        s_prev = s
    power = s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2
    return (rms, power)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="Deurbel", help="Reolink config entry title (default: Deurbel)")
    ap.add_argument("--seconds", type=float, default=6.0, help="Capture duration (default: 6s)")
    ap.add_argument("--rtsp-path", default="h264Preview_01_main", help="RTSP path after host:554/ (default: h264Preview_01_main)")
    ap.add_argument("--freq", type=int, default=1000, help="Talk test tone frequency (Hz, default: 1000)")
    ap.add_argument("--talk-duration", type=float, default=2.0, help="Talk tone duration (seconds, default: 2)")
    ap.add_argument("--talk-volume", type=float, default=8.0, help="Software volume multiplier for talk (default: 8)")
    args = ap.parse_args(argv)

    e = _get_reolink_entry(args.title)
    host = e["host"]
    user = e["username"]
    pw = e["password"]
    if not host or not user or not pw:
        raise SystemExit("Missing host/username/password in config entry")

    rtsp_url = f"rtsp://{user}:{pw}@{host}:554/{args.rtsp_path}"
    baseline = ROOT / "media" / "reolink_talk_baseline.wav"
    during = ROOT / "media" / "reolink_talk_during_talk.wav"

    print(f"RTSP: {rtsp_url.replace(pw, '***')}")
    print(f"Capture baseline -> {baseline}")
    _capture_rtsp_wav(url=rtsp_url, seconds=float(args.seconds), out_path=baseline)

    print(f"Capture during talk -> {during}")
    # Start capture first, then fire talk after ~1s so the tone lands inside the file.
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cap_cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        rtsp_url,
        "-t",
        str(float(args.seconds)),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(during),
    ]
    cap = subprocess.Popen(cap_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        time.sleep(1.0)
        talk_cmd = [
            sys.executable,
            str(ROOT / "scripts" / "reolink_talk_debug.py"),
            "--title",
            str(args.title),
            "--sine",
            str(int(args.freq)),
            "--duration",
            str(float(args.talk_duration)),
            "--volume",
            str(float(args.talk_volume)),
            "--blocks-per-payload",
            "1",
            "--bcmedia-mode",
            "bytes_half",
            "--override-stream-mode",
            "mixAudioStream",
        ]
        subprocess.run(talk_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
        _, err = cap.communicate(timeout=60)
        if cap.returncode != 0:
            raise RuntimeError((err or b"").decode("utf-8", "ignore")[:800])
    finally:
        try:
            cap.kill()
        except Exception:
            pass

    rms0, p0 = _goertzel_power_1khz(baseline, freq_hz=float(args.freq))
    rms1, p1 = _goertzel_power_1khz(during, freq_hz=float(args.freq))
    print(f"Baseline: rms={rms0:.6f} power@{args.freq}Hz={p0:.2f}")
    print(f"During  : rms={rms1:.6f} power@{args.freq}Hz={p1:.2f}")
    if p1 > p0 * 2.0:
        print("RESULT: tone detected in RTSP capture (speaker likely played, mic picked it up).")
    else:
        print("RESULT: no clear tone increase detected (speaker might be silent, or mic didn't pick it up).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

