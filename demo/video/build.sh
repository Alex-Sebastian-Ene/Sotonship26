#!/usr/bin/env bash
# Build the pitch-video overlays with Boby's `creative` CLI.
# One Boby project per overlay, exported as a transparent PNG into demo/video/out/.
# Drop the PNGs over the tripod/screen footage in any editor (CapCut, Premiere, DaVinci).
#
# Prereq: bash demo/video/setup.sh  (installs Boby, links `creative`).
# Run from the repo root:  bash demo/video/build.sh
#
# NOTE: authored against Boby's documented CLI; not yet run end-to-end here.
# If a flag name drifts, check `creative --help` / `creative skills get boby`.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OV="$HERE/overlays"
OUT="$HERE/out"
mkdir -p "$OUT"

if ! command -v creative >/dev/null 2>&1; then
  echo "creative CLI not found. Run: bash demo/video/setup.sh" >&2
  exit 1
fi

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
  # (e.g. the `end` overlay has no end.css, so an unconditional --css fails ENOENT.)
  local css_args=()
  [ -f "$OV/$tmpl.css" ] && css_args=(--css "$OV/$tmpl.css")

  # Create a 1920x1080 project; capture its project + frame ids.
  local json pid fid
  json="$(creative project create --name "sotonship-$name" --preset landscape --json)"
  pid="$(echo "$json" | python3 -c 'import sys,json;print(json.load(sys.stdin)["project"]["id"])')"
  fid="$(echo "$json" | python3 -c 'import sys,json;print(json.load(sys.stdin)["project"]["frames"][0]["id"])')"

  # A non-device Boby project defaults the frame background to solid white, which
  # paints over the card's own `background:transparent`. Clear it so the export
  # keeps its alpha channel (color-type 6 RGBA) instead of rendering opaque white.
  creative apply --project "$pid" \
    --command '{"label":"transparent bg","commands":[{"op":"element.setBackground","frameId":"'"$fid"'","background":{"type":"none"}}]}'

  # Lay the overlay into the frame, filling it; copy comes from the params file.
  creative code set --project "$pid" --frame "$fid" \
    --html "$OV/$tmpl.html" "${css_args[@]}" --params "$OV/$params" --fill --name "$name"

  # Export a transparent PNG (Remotion renders alpha where the canvas is transparent).
  creative export --project "$pid" --frame "$fid" --format png --out "$OUT/$name.png"
  echo "built $OUT/$name.png"
}

for row in "${OVERLAYS[@]}"; do
  # shellcheck disable=SC2086
  set -- $row
  build_one "$1" "$2" "$3"
done

echo
echo "Overlays in $OUT/. Composite them over your footage per the beat sheet in demo/video/README.md."
echo "For moving title/scale/end cards, animate with: creative motion enter/move  (see 'creative skills get boby motion')."
