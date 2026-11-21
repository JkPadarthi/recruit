"""The APK download card and route.

The failure that matters: a card pointing at a file that is not there, or a download
served with the wrong Content-Type so Android saves a blob instead of offering Install.
"""
import json

import pytest


@pytest.fixture()
def apk_dir(tmp_path, monkeypatch):
    d = tmp_path / "apk"
    d.mkdir()
    monkeypatch.setenv("APK_DIR", str(d))
    return d


def _publish(d, version="1.1.6", size=1024):
    (d / "recruit.apk").write_bytes(b"PK\x03\x04" + b"x" * size)
    (d / "apk.json").write_text(json.dumps({
        "version": version, "size_bytes": size, "sha256": "abc",
        "built_at": "2026-11-21T23:52:10+05:30", "notes": "test build",
    }))


@pytest.mark.asyncio
async def test_no_build_means_no_card_and_no_download(client, apk_dir):
    assert (await client.get("/api/app")).json() == {"available": False}
    assert (await client.get("/download")).status_code == 404


@pytest.mark.asyncio
async def test_manifest_reports_the_published_build(client, apk_dir):
    _publish(apk_dir)
    body = (await client.get("/api/app")).json()
    assert body["available"] is True
    assert body["version"] == "1.1.6"
    assert body["size_mb"] >= 0


@pytest.mark.asyncio
async def test_download_is_typed_for_android(client, apk_dir):
    _publish(apk_dir)
    r = await client.get("/download")
    assert r.status_code == 200
    # Android only offers "Install" for this type; a generic octet-stream saves a blob.
    assert r.headers["content-type"] == "application/vnd.android.package-archive"
    assert "recruit-v1.1.6.apk" in r.headers["content-disposition"]


@pytest.mark.asyncio
async def test_strip_appears_below_the_login_form(client, register, apk_dir):
    _publish(apk_dir)
    html = (await client.get("/login")).text
    assert "Get the Android app" in html
    assert 'href="/app"' in html
    # Regression: the include once landed inside the bodyclass block, so the markup
    # was emitted inside class="..." and the page rendered as garbage.
    assert html.index("Get the Android app") > html.index('<main class="auth">')
    assert 'class="auth-page<' not in html


@pytest.mark.asyncio
async def test_the_app_page_explains_the_install(client, apk_dir):
    _publish(apk_dir)
    html = (await client.get("/app")).text
    for needle in ("Download APK", "v1.1.6", "Allow from this source",
                   "Add to Home Screen", "sha256"):
        assert needle in html, needle
    assert 'href="/download"' in html


@pytest.mark.asyncio
async def test_the_app_page_says_so_when_nothing_is_published(client, apk_dir):
    html = (await client.get("/app")).text
    assert "No build published yet" in html


@pytest.mark.asyncio
async def test_no_card_on_the_login_page_without_a_build(client, apk_dir):
    html = (await client.get("/login")).text
    assert "Get the Android app" not in html
