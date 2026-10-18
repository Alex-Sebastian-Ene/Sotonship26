import asyncio
import json
import subprocess
import sys

import edge_tts

RATE = sys.argv[1] if len(sys.argv) > 1 else "+12%"


async def one(k, t):
    await edge_tts.Communicate(t, "en-GB-RyanNeural", rate=RATE).save(f"vo/{k}.mp3")


async def main():
    lines = json.load(open("vo.json", encoding="utf-8"))
    await asyncio.gather(*(one(k, t) for k, t in lines))
    tot = 0
    out = {}
    for k, _ in lines:
        d = float(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    f"vo/{k}.mp3",
                ]
            ).decode()
        )
        out[k] = round(d, 2)
        tot += d
        print(f"{k:9s} {d:5.1f}")
    print("total", round(tot, 1))
    json.dump(out, open("vo/durations.json", "w"))


asyncio.run(main())
