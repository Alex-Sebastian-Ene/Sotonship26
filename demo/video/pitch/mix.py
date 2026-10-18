"""Place each narration clip at its timeline time, normalise loudness, and mux with the frames."""

import json
import subprocess

tl = json.load(open("timeline.json"))
args = ["ffmpeg", "-y", "-v", "error"]
for a in tl["audio"]:
    args += ["-i", f"vot/{a['k']}.wav"]
parts = [
    f"[{i}:a]adelay={int(a['at'] * 1000)}|{int(a['at'] * 1000)}[a{i}]"
    for i, a in enumerate(tl["audio"])
]
fl = (
    ";".join(parts)
    + ";"
    + "".join(f"[a{i}]" for i in range(len(tl["audio"])))
    + f"amix=inputs={len(tl['audio'])}:normalize=0,apad=whole_dur={tl['total']:.2f},loudnorm=I=-16:TP=-1.5:LRA=11[o]"
)
subprocess.run(
    args + ["-filter_complex", fl, "-map", "[o]", "-ar", "48000", "-ac", "2", "vo_mix.wav"],
    check=True,
)
subprocess.run(
    [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-framerate",
        "25",
        "-i",
        "out/%05d.jpg",
        "-i",
        "vo_mix.wav",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "19",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        "sotonship26-pitch.mp4",
    ],
    check=True,
)
print(
    subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-of",
            "csv=p=0",
            "sotonship26-pitch.mp4",
        ]
    ).decode()
)
