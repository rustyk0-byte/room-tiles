#!/bin/sh
# Build the dashboard locally - the same steps as CI's Frontend workflow
# (typecheck, tests, the colours rule, bundle, per-theme artwork) - straight
# into custom_components/room_tiles/frontend, where HA serves it from.
# Needs Node.js + npm (Alpine: apk add nodejs npm) and Python with Pillow.
#   tools/build-frontend.sh          everything
#   tools/build-frontend.sh --quick  skip the tests (typecheck + build only)
set -e
cd "$(dirname "$0")/../frontend"
[ -d node_modules ] || npm install --no-audit --no-fund
npm run --silent typecheck
[ "$1" = "--quick" ] || npm test --silent
# colorpicker.ts computes the LIGHT's colours (data, not theme)
if grep -nE "#[0-9a-fA-F]{3,8}\b|rgba?\(|var\(--(primary|secondary|card|state|ha-|paper)" src/*.ts | grep -v "^src/theme.ts:" | grep -v "^src/colorpicker.ts:"; then
  echo "Hard-coded colour or HA theme variable outside src/theme.ts" && exit 1
fi
npm run --silent build
# the Dark / Light themes' off pictures (from their icons + colours)
python3 ../assets/tools/make_off_icons.py >/dev/null
python3 ../assets/build_web.py ../custom_components/room_tiles/frontend
# the wall panels' packs share the art masters, the theme tokens and the
# string tables: rebuilt with the dashboard so they never fall behind
python3 ../assets/build_panel.py >/dev/null
echo "Built: $(cat ../custom_components/room_tiles/frontend/version.json)"
