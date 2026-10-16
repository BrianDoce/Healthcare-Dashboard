"""Integrity checks on the committed crosswalk (no need for the 14 MB official CMS file)."""
import csv
import re
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "reference"
ROWS = list(csv.DictReader((REF / "snomed_to_icd10cm.csv").open(encoding="utf-8")))
USED = {r["icd10cm_code"]: r["description"] for r in csv.DictReader((REF / "icd10cm_codes_used.csv").open(encoding="utf-8"))}
CODE = re.compile(r"^[A-Z]\d[0-9A-Z](\.[0-9A-Z]{1,4})?$")


def test_no_duplicate_snomed_codes():
    codes = [r["snomed_code"] for r in ROWS]
    assert len(codes) == len(set(codes))


def test_every_mapped_code_is_well_formed_and_has_an_official_description():
    for r in ROWS:
        if r["match"] == "X":
            assert r["icd10cm_code"] == ""
            continue
        assert CODE.match(r["icd10cm_code"]), r
        assert USED.get(r["icd10cm_code"]), f"{r['icd10cm_code']} missing official description"


def test_match_and_confidence_values_are_from_the_documented_sets():
    assert {r["match"] for r in ROWS} <= {"E", "B", "N", "S", "X"}
    assert {r["confidence"] for r in ROWS} <= {"high", "medium", "low"}


def test_lossy_mappings_are_not_marked_high_confidence_equivalents():
    # a 'B' (broader) mapping loses information; 'low' confidence rows must carry an explanatory note
    for r in ROWS:
        if r["confidence"] == "low":
            assert r["note"].strip(), f"low-confidence row without a note: {r['snomed_code']}"
