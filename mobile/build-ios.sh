#!/usr/bin/env bash
# Build the iOS app and upload it to TestFlight. RUNS ON THE MAC, not on bharat.
#
#   APPLE_TEAM_ID=ABCDE12345 \
#   ASC_KEY_ID=XXXXXXXXXX \
#   ASC_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
#   ./mobile/build-ios.sh
#
# The three IDs come from:
#   APPLE_TEAM_ID  developer.apple.com → Membership (10 chars)
#   ASC_KEY_ID     App Store Connect → Users and Access → Integrations (10 chars)
#   ASC_ISSUER_ID  same page (UUID, shown above the key list)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${APPLE_TEAM_ID:?set APPLE_TEAM_ID (developer.apple.com → Membership)}"
: "${ASC_KEY_ID:?set ASC_KEY_ID (App Store Connect → Integrations)}"
: "${ASC_ISSUER_ID:?set ASC_ISSUER_ID (same page)}"

# Xcode 15.3+ wants app-store-connect; older Xcode only knows app-store.
EXPORT_METHOD="${IOS_EXPORT_METHOD:-app-store-connect}"

fail() { echo "!! $*" >&2; exit 1; }

echo "==> checking the Mac is ready"
command -v flutter >/dev/null || fail "flutter not on PATH (install the SDK, then re-run)"
xcodebuild -version >/dev/null 2>&1 || fail "Xcode missing — install it, then: sudo xcode-select -s /Applications/Xcode.app"
[ -f "$HERE/ios/Runner/GoogleService-Info.plist" ] || \
  fail "ios/Runner/GoogleService-Info.plist missing — download it from the Firebase console (project recruit-101d5 → add iOS app com.jkpadarthi.recruit)"

VERSION="$(grep -m1 '^version:' "$HERE/pubspec.yaml" | sed 's/version: *//')"
BUILD_NUMBER="${VERSION#*+}"
[ "$BUILD_NUMBER" = "$VERSION" ] && fail "pubspec version has no +build number; TestFlight needs one that increases every upload"
echo "    version $VERSION (CFBundleVersion $BUILD_NUMBER)"

echo "==> flutter pub get"
(cd "$HERE" && flutter pub get >/dev/null)

EXPORT_PLIST="$(mktemp -t exportoptions).plist"
cat > "$EXPORT_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>method</key><string>$EXPORT_METHOD</string>
	<key>teamID</key><string>$APPLE_TEAM_ID</string>
	<key>signingStyle</key><string>automatic</string>
	<key>uploadSymbols</key><true/>
	<key>stripSwiftSymbols</key><true/>
</dict>
</plist>
PLIST

echo "==> building the ipa (this is the slow part)"
(cd "$HERE" && flutter build ipa --release --export-options-plist="$EXPORT_PLIST")

IPA="$HERE/build/ios/ipa/recruit.ipa"
[ -f "$IPA" ] || IPA="$(find "$HERE/build/ios/ipa" -name '*.ipa' -maxdepth 1 | head -1)"
[ -n "${IPA:-}" ] && [ -f "$IPA" ] || fail "no .ipa produced — signing almost certainly failed; open ios/Runner.xcworkspace, pick the team, and add the Push Notifications capability"

echo "==> uploading $IPA to TestFlight"
# altool is deprecated in name only; it still carries the upload and is the only
# path that works without opening Xcode's Organizer by hand.
xcrun altool --upload-app --type ios --file "$IPA" \
  --api-key "$ASC_KEY_ID" --api-issuer "$ASC_ISSUER_ID" \
  || fail "upload failed — check the API key role (needs App Manager) and that the bundle id matches the App Store Connect record"

echo
echo "Route open. TestFlight takes 5-15 min to process, then the build appears"
echo "under the app's TestFlight tab: add the testers, they accept, they install."
echo "Remember: this build expires 90 days after upload."
