#!/usr/bin/env python3
"""Print the versionName baked into an APK, or exit 1 if none is found.

Android's binary AndroidManifest.xml keeps a UTF-16 string pool, so neither grep
nor `strings` sees versionName. Used by build-apk.sh to prove the APK it just
pulled is the build it thinks it is.
"""
import re
import sys
import zipfile

if len(sys.argv) != 2:
    sys.exit("usage: apk_version.py <apk>")

with zipfile.ZipFile(sys.argv[1]) as z:
    raw = z.read("AndroidManifest.xml")

for run in re.findall(rb"(?:[\x20-\x7e]\x00){3,}", raw):
    s = run.decode("utf-16-le")
    if re.fullmatch(r"\d+\.\d+\.\d+", s):
        print(s)
        break
else:
    sys.exit("no versionName found in AndroidManifest.xml")
