#!/bin/zsh
set -euo pipefail

desktop_source=${0:A:h}
market_project=${desktop_source:h}
target="$HOME/Desktop/Factor Lab 行情看板.app"
if [[ -e "$target" ]]; then
  print -u2 "桌面上已经有 Factor Lab 行情看板.app，请保留或移动现有应用后再安装。"
  exit 1
fi

build_directory=$(mktemp -d "$HOME/Desktop/.factor-lab-build.XXXXXX")
trap 'rm -rf -- "$build_directory"' EXIT
bundle="$build_directory/Factor Lab 行情看板.app"
mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"
swiftc -O -parse-as-library "$desktop_source/MarketLauncher.swift" -o "$bundle/Contents/MacOS/MarketLauncher"
icon_source="$desktop_source/AppIcon.png"
iconset="$build_directory/AppIcon.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$icon_source" --out "$iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size*2))
  sips -z "$double" "$double" "$icon_source" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$bundle/Contents/Resources/AppIcon.icns"
/usr/bin/python3 - "$bundle/Contents/Info.plist" "$market_project" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "wb") as file:
    plistlib.dump({
        "CFBundleIdentifier": "local.factorlab.market-dashboard",
        "CFBundleName": "Factor Lab 行情看板",
        "CFBundleDisplayName": "Factor Lab 行情看板",
        "CFBundleExecutable": "MarketLauncher",
        "CFBundleIconFile": "AppIcon.icns",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "2.0",
        "CFBundleVersion": "2",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        "MarketProjectPath": sys.argv[2],
    }, file)
PY
plutil -lint "$bundle/Contents/Info.plist"
codesign --force --sign - "$bundle"
mv "$bundle" "$target"
print "$target"
