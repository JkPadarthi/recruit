"""Deterministic extraction + classification."""
from app.extract import classify, extract_ids


def test_extract_ids_from_csv_like_body():
    ids = extract_ids("Selected: 23BAI0021, Kartheek 23BAI0056 and V1C2P5I6.")
    assert "23BAI0021" in ids
    assert "23BAI0056" in ids
    assert "V1C2P5I6" in ids


def test_extract_ids_ignores_noise():
    ids = extract_ids("Meeting QS2026 at 10am, reg no 12345678")
    assert ids == set()


def test_classify_spreadsheet_always_shortlist():
    assert classify("Re: drive", "no keywords", set(), True) == "shortlist"


def test_classify_result_keyword():
    assert classify("Selection List", "contains Final List text", set(), False) == "shortlist"


def test_classify_embedded_ids_shortlist():
    assert classify("Results", "23BAI0021 listed here", {"23BAI0021"}, False) == "shortlist"


def test_classify_plain_announcement():
    assert classify("Internship drive", "sharing details", set(), False) == "announcement"