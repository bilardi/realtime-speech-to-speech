"""Measure end-to-end latency from a recording with both Italian and English speech.

The recording is expected to contain Italian on the first half (PC mic side) and
English on the second half (mobile output side). The script finds the onset of speech
in each half via simple energy thresholding and reports the delta in milliseconds.

Uses `wave` from stdlib and `numpy` (no scipy dependency).
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

_WINDOW_SECONDS = 0.02
_DEFAULT_THRESHOLD_DB = -40.0
_INT16_MAX = 32768
_MS_PER_SECOND = 1000
_EXPECTED_ARGV_LEN = 2


def _read_wav(path: Path) -> tuple[int, np.ndarray]:
    """Return ``(sample_rate, mono int16 samples)`` from a WAV file using stdlib ``wave``."""
    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
    samples = np.frombuffer(raw, dtype=np.int16)
    if n_channels > 1:
        samples = samples.reshape(-1, n_channels)[:, 0]
    return sample_rate, samples


def find_speech_onset(
    samples: np.ndarray,
    sample_rate: int,
    threshold_db: float = _DEFAULT_THRESHOLD_DB,
) -> int:
    """Return the index of the first sample whose RMS over a 20 ms window exceeds threshold."""
    window = int(_WINDOW_SECONDS * sample_rate)
    rms_threshold = 10 ** (threshold_db / 20)
    for start in range(0, len(samples) - window, window):
        chunk = samples[start : start + window].astype(np.float64) / _INT16_MAX
        rms = float(np.sqrt(np.mean(chunk * chunk)))
        if rms > rms_threshold:
            return start
    return -1


def measure(path: Path) -> float:
    """Return the end-to-end latency in milliseconds based on speech onsets in two halves."""
    sample_rate, samples = _read_wav(path)
    half = len(samples) // 2
    onset_it = find_speech_onset(samples[:half], sample_rate)
    onset_en = find_speech_onset(samples[half:], sample_rate)
    if onset_it < 0 or onset_en < 0:
        msg = "could not detect speech onset in one of the halves"
        raise RuntimeError(msg)

    delta_samples = (half + onset_en) - onset_it
    return delta_samples * _MS_PER_SECOND / sample_rate


def main() -> None:
    """Print the end-to-end latency for the WAV recording given on the command line."""
    if len(sys.argv) != _EXPECTED_ARGV_LEN:
        print("usage: measure_e2e.py <recording.wav>", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    delta_ms = measure(Path(sys.argv[1]))
    print(f"end-to-end latency: {delta_ms:.0f} ms")  # noqa: T201


if __name__ == "__main__":
    main()
