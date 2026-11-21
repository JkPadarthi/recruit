#!/usr/bin/env bash
# Build the debug APK on jengas-linux (WSL2, x86_64) — the only box here that can.
# `bharat` is a Pi 5: aapt2/r8 ship x86_64-only binaries, so the build cannot run there.
#
# Usage (from bharat):
#   ./android/build-on-jengas.sh              # build + copy the APK back to ~/Downloads
#
# Toolchain lives in jaswanth@100.99.54.8:~/android-build (JDK 17, SDK 35, Gradle 8.9),
# installed there without root. Remove it with: rm -rf ~/android-build
set -euo pipefail

HOST="${HOST:-jaswanth@100.99.54.8}"
REMOTE_DIR="${REMOTE_DIR:-android-build}"
OUT="${OUT:-$HOME/Downloads/recruit-android-debug.apk}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> syncing source to $HOST:~/$REMOTE_DIR/android"
tar czf - -C "$HERE/.." android | ssh "$HOST" \
  "mkdir -p ~/$REMOTE_DIR/android && tar xzf - -C ~/$REMOTE_DIR/android --strip-components=1"

echo "==> building (this is the slow one: first run pulls AGP/Kotlin deps)"
ssh "$HOST" "cd ~/$REMOTE_DIR/android && echo 'sdk.dir='\$HOME/'$REMOTE_DIR/sdk' > local.properties && \
  env JAVA_HOME=\$HOME/$REMOTE_DIR/tools/jdk17 ANDROID_HOME=\$HOME/$REMOTE_DIR/sdk \
      PATH=\$HOME/$REMOTE_DIR/tools/jdk17/bin:\$PATH \
      \$HOME/$REMOTE_DIR/tools/gradle-8.9/bin/gradle :app:assembleDebug --no-daemon --console=plain \
  | tail -20"

echo "==> fetching APK"
scp -q "$HOST:~/$REMOTE_DIR/android/app/build/outputs/apk/debug/app-debug.apk" "$OUT"
ls -lh "$OUT"
echo "==> install: adb install -r $(basename "$OUT")   (or copy to the phone and tap it)"
