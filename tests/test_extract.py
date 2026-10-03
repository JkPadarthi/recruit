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


# ---- final-outcome detection (selection vs shortlist) ----------------------
from app.extract import detect_outcome


def test_detect_outcome_final_selection_congrats():
    # Deloitte-style: final selection list -> celebrate
    assert detect_outcome("Congratulations!! Deloitte India Dream Internship / "
                          "Placement Offer Selection List - 2027 Batch",
                          "23BAI0056 has been selected.") == "selection"


def test_detect_outcome_offer_letter_is_selection():
    assert detect_outcome("Offer Letter", "You have been selected for the role") == "selection"


def test_detect_outcome_bare_shortlist_is_not_selection():
    # "Congratulations! You are shortlisted" is a shortlist, NOT a win
    assert detect_outcome("Congratulations!", "You have been shortlisted for the online test") == "shortlist"


def test_detect_outcome_neutral_result_is_shortlist():
    assert detect_outcome("Results", "23BAI0021 listed here") == "shortlist"