#!/usr/bin/env bash
# Build the pitch-video overlays with Boby's `creative` CLI, in three formats each:
#   <name>.png   transparent still   (RGBA, color-type 6, corner alpha 0)
#   <name>.webm  animated, with alpha (VP9, alpha_mode=1) -- the drop-over-footage asset
#   <name>.mp4   animated, H.264      (no alpha; the card flattened on the UI page bg)
# One Boby project per overlay. PNG + an alpha ProRes master come straight from the
# `creative` CLI; the webm/mp4 are transcoded from that master with ffmpeg (Boby's own
# webm export is VP8 without alpha, and mp4 cannot carry alpha at all).
#
# Drop the PNG/WebM over the tripod/screen footage in any editor (CapCut, Premiere,
# DaVinci). The MP4 is a standalone preview: it shows the card on the light UI page
# background #F4F6F8 (0xF4F6F8), since H.264 has no transparency.
#
# Prereq: bash demo/video/setup.sh  (installs Boby, links `creative`), plus ffmpeg.
# Run from the repo root:  bash demo/video/build.sh
# Override the output dir:  OUT=/path/to/dir bash demo/video/build.sh
#
# NOTE: authored against Boby's documented CLI.
# If a flag name drifts, check `creative --help` / `creative skills get boby`.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OV="$HERE/overlays"
OUT="${OUT:-$HERE/out}"
mkdir -p "$OUT"

# UI page background the MP4s are flattened onto (light theme).
PAGE_BG="0xF4F6F8"
FPS=30
DUR=150          # composition length in frames (5s @ 30fps; caller trims)

if ! command -v creative >/dev/null 2>&1; then
  echo "creative CLI not found. Run: bash demo/video/setup.sh" >&2
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg not found (needed for the webm/mp4 transcodes)." >&2
  exit 1
fi

jqpy() { python3 -I -c "import sys,json;print(json.load(sys.stdin)$1)"; }

# overlay-name  template  params-file
# (stat is one template reused with several params files.)
OVERLAYS=(
  "title     title    title.params.json"
  "quote     quote    quote.params.json"
  "stat-scale  stat   stat-scale.params.json"
  "stat-saving stat   stat-saving.params.json"
  "stat-anchor stat   stat-anchor.params.json"
  "stat-skill  stat   stat-skill.params.json"
  "caption   caption  caption.params.json"
  "scale     scale    scale.params.json"
  "end       end      end.params.json"
)

build_one() {
  local name="$1" tmpl="$2" params="$3"
  [ -f "$OV/$tmpl.html" ] || { echo "missing $OV/$tmpl.html" >&2; return 1; }

  # --css is optional in the CLI; only pass it when a matching stylesheet exists.
  # (e.g. the `end` overlay historically had no end.css; an unconditional --css fails ENOENT.)
  local css_args=()
  [ -f "$OV/$tmpl.css" ] && css_args=(--css "$OV/$tmpl.css")

  # Create a 1920x1080 project; capture its project + frame ids.
  local json pid fid eid cid
  json="$(creative project create --name "sotonship-$name" --preset landscape --json)"
  pid="$(echo "$json" | jqpy '["project"]["id"]')"
  fid="$(echo "$json" | jqpy '["project"]["frames"][0]["id"]')"

  # A non-device Boby project defaults the frame background to solid white, which
  # paints over the card's own `background:transparent`. Clear it so PNG + ProRes
  # keep their alpha channel instead of rendering opaque white (the PR #64 fix).
  creative apply --project "$pid" \
    --command '{"label":"transparent bg","commands":[{"op":"element.setBackground","frameId":"'"$fid"'","background":{"type":"none"}}]}' >/dev/null

  # Lay the overlay into the frame, filling it; copy comes from the params file.
  eid="$(creative code set --project "$pid" --frame "$fid" \
    --html "$OV/$tmpl.html" "${css_args[@]}" --params "$OV/$params" --fill --name "$name" --json \
    | jqpy '["id"]')"

  # A composition on the frame's timeline, for the animated exports.
  cid="$(creative apply --project "$pid" --json \
    --command '{"label":"comp","commands":[{"op":"composition.add","composition":{"frameId":"'"$fid"'","name":"'"$name"'-anim","fps":'"$FPS"',"durationFrames":'"$DUR"'}}]}' \
    | jqpy '["results"][0]["createdIds"][0]')"

  # Subtle, short motion: fade+rise enter (~15f, decelerate), hold, fade exit (accelerate).
  creative apply --project "$pid" \
    --command '{"label":"motion","commands":[{"op":"motion.enter","compositionId":"'"$cid"'","elementIds":["'"$eid"'"],"at":0,"from":{"y":40,"opacity":0},"token":"enter","frames":15},{"op":"motion.exit","compositionId":"'"$cid"'","elementIds":["'"$eid"'"],"at":132,"to":{"y":-24,"opacity":0},"token":"exit"}]}' >/dev/null

  # 1) Transparent still (card at rest).
  creative export --project "$pid" --frame "$fid" --format png --out "$OUT/$name.png" >/dev/null

  # 2) Alpha master: ProRes 4444 (yuva444p) -- the only Boby export that keeps alpha.
  local mov="$OUT/.$name.master.mov"
  creative export --project "$pid" --composition "$cid" --format mov --out "$mov" >/dev/null

  # 3) Alpha WebM (VP9, alpha_mode=1) -- the true drop-over-footage animated asset.
  ffmpeg -y -loglevel error -i "$mov" \
    -c:v libvpx-vp9 -pix_fmt yuva420p -b:v 0 -crf 24 -an "$OUT/$name.webm"

  # 4) H.264 MP4 -- no alpha, so flatten the card onto the UI page background.
  ffmpeg -y -loglevel error -f lavfi -i "color=c=$PAGE_BG:s=1920x1080:r=$FPS" -i "$mov" \
    -filter_complex "[0:v][1:v]overlay=shortest=1,format=yuv420p[v]" -map "[v]" \
    -c:v libx264 -crf 18 -pix_fmt yuv420p -an "$OUT/$name.mp4"

  rm -f "$mov"
  echo "built $OUT/$name.{png,webm,mp4}"
}

for row in "${OVERLAYS[@]}"; do
  # shellcheck disable=SC2086
  set -- $row
  build_one "$1" "$2" "$3"
done

echo
echo "Overlays in $OUT/ (png + alpha webm + flattened mp4). Composite the PNG/WebM over"
echo "your footage per the beat sheet in demo/video/README.md."
