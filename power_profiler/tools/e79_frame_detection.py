"""Compatibility import for the shared acquisition/offline frame detector."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radio_power_profiler.frame_detection import detect_frames, _sustained_groups

__all__ = ["detect_frames"]
