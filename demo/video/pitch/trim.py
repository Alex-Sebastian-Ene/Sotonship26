"""Trim leading and trailing silence from each narration clip and record its length (vot/durations.json)."""

import json
import subprocess
from pathlib import Path

F = (
    "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
    "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.12,areverse"
)
Path("vot").mkdir(exist_ok=True)
out = {}
for k, _ in json.load(open("vo.json", encoding="utf-8")):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            f"vo/{k}.mp3",
            "-af",
            F,
            "-ar",
            "48000",
            "-ac",
            "2",
            f"vot/{k}.wav",
        ],
        check=True,
    )
    out[k] = round(
        float(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    f"vot/{k}.wav",
                ]
            ).decode()
        ),
        3,
    )
json.dump(out, open("vot/durations.json", "w"))
print(out, "total", round(sum(out.values()), 1))
