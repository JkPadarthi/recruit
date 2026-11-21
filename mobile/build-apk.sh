#!/usr/bin/env bash
# Build the Flutter client on jengas (x86_64 WSL2) and fetch the APK to ~/Downloads.
#
#   ./mobile/build-apk.sh            # release, split per ABI (what you sideload)
#   ./mobile/build-apk.sh --debug    # debug build, split per ABI, for flutter logs
#
# iOS needs macOS: `flutter build ios` from the M5, which is why the Dart code
# lives in one place and the platform folders are generated per host.
set -euo pipefail

HOST="${HOST:-jaswanth@100.99.54.8}"
REMOTE="${REMOTE:-flutter-work/recruit_mobile}"
MODE="${1:-release}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> syncing Dart + Android config to $HOST:~/$REMOTE"
# NOTE: tar from the PARENT of mobile/ and strip exactly one component, so the
# paths land as lib/... and android/... on the remote. Taring from inside mobile/
# with --strip-components=1 silently turns android/settings.gradle.kts into
# settings.gradle.kts at the root, which changes nothing and looks like success.
# res/ MUST be in this list: the launcher icons live there, and a build that skips
# it keeps the old icon while everything else updates.
tar czf - -C "$HERE/.." \
  mobile/lib mobile/assets mobile/pubspec.yaml mobile/pubspec.lock \
  mobile/android/settings.gradle.kts mobile/android/build.gradle.kts \
  mobile/android/app/build.gradle.kts mobile/android/app/google-services.json \
  mobile/android/app/src/main/AndroidManifest.xml \
  mobile/android/app/src/main/res \
  mobile/android/app/src/main/kotlin \
  | ssh "$HOST" "tar xzf - -C ~/$REMOTE --strip-components=1"

if [ "$MODE" = "--debug" ]; then
  FLAGS="--debug --split-per-abi"; OUT_NAME="app-arm64-v8a-debug.apk"; LOCAL="recruit-flutter-arm64-debug.apk"
else
  FLAGS="--release --split-per-abi"; OUT_NAME="app-arm64-v8a-release.apk"; LOCAL="recruit-flutter-arm64.apk"
fi

echo "==> building ($FLAGS)"
ssh "$HOST" "rm -f ~/flutter-build.log; cd ~/$REMOTE && setsid nohup env \
    PATH=\$HOME/flutter/bin:\$HOME/android-build/tools/jdk17/bin:\$PATH \
    JAVA_HOME=\$HOME/android-build/tools/jdk17 ANDROID_HOME=\$HOME/android-build/sdk \
    flutter build apk $FLAGS > ~/flutter-build.log 2>&1 < /dev/null & \
  for i in \$(seq 1 120); do sleep 5; grep -q 'Built build/app/outputs' ~/flutter-build.log && break; \
    grep -q 'FAILURE\|Gradle task assemble.* failed' ~/flutter-build.log && break; done; \
  tail -6 ~/flutter-build.log"

# A failed Gradle run leaves the PREVIOUS apk in build/outputs. Copying it would
# report success and ship an old binary under a new version number, so trust the
# log, not the presence of a file.
if ! ssh "$HOST" "grep -q 'Built build/app/outputs' ~/flutter-build.log"; then
  echo "!! BUILD FAILED — refusing to fetch a stale APK" >&2
  ssh "$HOST" "grep -E '^e: |What went wrong|error:' ~/flutter-build.log | head -15" >&2 || true
  exit 1
fi

echo "==> fetching APK"
scp -q "$HOST:~/$REMOTE/build/app/outputs/flutter-apk/$OUT_NAME" "$HOME/Downloads/$LOCAL"

# Name it after the version it carries, so a phone full of downloads is readable
# and the operator can tell which build is installed. Prove the binary agrees
# before naming it — the whole point is not to lie about what this file is.
VERSION="$(grep -m1 '^version:' "$HERE/pubspec.yaml" | sed 's/version: *//; s/+.*//')"
ACTUAL="$(python3 "$HERE/tool/apk_version.py" "$HOME/Downloads/$LOCAL")"
if [ "$ACTUAL" != "$VERSION" ]; then
  echo "!! APK reports versionName '$ACTUAL' but pubspec says '$VERSION' — stale artifact, not shipping" >&2
  exit 1
fi
NAMED="$HOME/Downloads/recruit-v${VERSION}.apk"
cp -f "$HOME/Downloads/$LOCAL" "$NAMED"
ls -lh "$NAMED"

echo "==> install: adb install -r $LOCAL   (release is signed with the debug key for now)"
