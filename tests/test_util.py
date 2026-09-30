"""Register-ID normalization + looks_like_id rules (mirrors proven watcher tests)."""
from app.util import looks_like_id, normalize_id


def test_normalize_id_squashes_and_uppercases():
    assert normalize_id(" 23-bai 0021 ") == "23BAI0021"
    assert normalize_id("23bce.0654") == "23BCE0654"
    assert normalize_id("K3I6O4I8") == "K3I6O4I8"
    assert normalize_id("") == ""


def test_looks_like_register_id():
    assert looks_like_id("23BAI0021")
    assert looks_like_id("23BCE0654")
    assert not looks_like_id("23X0021")       # too few letters
    assert not looks_like_id("hello world")   # no digits, spaces


def test_looks_like_code_accepted():
    assert looks_like_id("K3I6O4I8")
    assert looks_like_id("V1C2P516")          # NOT strictly alternating


def test_looks_like_code_rejected():
    assert not looks_like_id("HELLOWORLD")    # no digits
    assert not looks_like_id("12345678")      # no letters
    assert not looks_like_id("QS2026")        # only 1 alternation