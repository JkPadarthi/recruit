#!/usr/bin/env bash
# Build the Flutter client on jengas (x86_64 WSL2) and fetch the APK to ~/Downloads.
#
#   ./mobile/build-apk.sh            # release, arm64 only (what you sideload)
#   ./mobile/build-apk.sh --debug    # debug build, all ABIs, for flutter logs
#
# iOS needs macOS: `flutter build ios` from the M5, which is why the Dart code
# lives in one place and the platform folders are generated per host.
set -euo pipefail

HOST="${HOST:-jaswanth@100.99.54.8}"
REMOTE="${REMOTE:-flutter-work/recruit_mobile}"
MODE="${1:-release}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> syncing Dart + Android config to $HOST:~/$REMOTE"
tar czf - -C "$HERE" lib pubspec.yaml pubspec.lock android/app/build.gradle.kts \
  android/app/src/main/AndroidManifest.xml \
  | ssh "$HOST" "tar xzf - -C ~/$REMOTE --strip-components=1"

if [ "$MODE" = "--debug" ]; then
  FLAGS="--debug --split-per-abi"; OUT_NAME="app-arm64-v8a-debug.apk"; LOCAL="recruit-flutter-arm64-debug.apk"
else
  FLAGS="--release --split-per-abi"; OUT_NAME="app-arm64-v8a-release.apk"; LOCAL="recruit-flutter-arm64.apk"
fi

echo "==> building ($FLAGS)"
ssh "$HOST" "cd ~/$REMOTE && setsid nohup env \
    PATH=\$HOME/flutter/bin:\$HOME/android-build/tools/jdk17/bin:\$PATH \
    JAVA_HOME=\$HOME/android-build/tools/jdk17 ANDROID_HOME=\$HOME/android-build/sdk \
    flutter build apk $FLAGS > ~/flutter-build.log 2>&1 < /dev/null & \
  for i in \$(seq 1 90); do sleep 5; grep -q 'Built build/app/outputs' ~/flutter-build.log && break; \
    grep -q 'FAILURE\|Gradle task assemble.* failed' ~/flutter-build.log && break; done; \
  tail -5 ~/flutter-build.log"

echo "==> fetching APK"
scp -q "$HOST:~/$REMOTE/build/app/outputs/flutter-apk/$OUT_NAME" "$HOME/Downloads/$LOCAL"
ls -lh "$HOME/Downloads/$LOCAL"
echo "==> install: adb install -r $LOCAL   (release is signed with the debug key for now)"
