#!/usr/bin/env bash
# Render every page background and the map outline with headless Chrome.
# Usage: bash powerbi/build/render_images.sh   (from the repository root)
set -e
C="/c/Program Files/Google/Chrome/Application/chrome.exe"
D="$(cd powerbi && pwd -W)"
PROFILE="${TMP:-/tmp}/cfpw-chrome-profile"
read -r ERR DIR <<<"$(python -c "import json;d=json.load(open('reports/forecast_backtest.json'));print(round(100*d['model']['median_abs_pct_error'],1), round(100*d['model']['direction_right_on_big_moves']))")"
shot() { "$C" --headless=new --user-data-dir="$PROFILE" --disable-gpu --hide-scrollbars --virtual-time-budget=8000 "$@" >/dev/null 2>&1; }
for p in overview markets foods regions forecast quality method; do
  shot --window-size=1280,720 --screenshot="$D/out/bg_$p.png" "file:///$D/design/page-sidebar.html?page=$p&err=$ERR&dir=$DIR"
done
shot --default-background-color=00000000 --window-size=860,1170 --screenshot="$D/out/map_outline_light.png" "file:///$D/design/map-outline.html?theme=light"
ls -la "$D/out" | grep -E "bg_(overview|markets|foods|regions|forecast|quality|method)|map_outline_light"
