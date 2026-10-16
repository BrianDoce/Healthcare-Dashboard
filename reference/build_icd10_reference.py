"""Validate the SNOMED->ICD-10-CM crosswalk against the official CMS ICD-10-CM code list.

    python reference/build_icd10_reference.py "<path>/icd10cm_order_2027.txt"

Source of the code list: https://www.cms.gov/files/zip/2027-code-descriptions-tabular-order.zip
Checks: every mapped code exists AND is billable (a leaf), no duplicate SNOMED codes, and (when the
pipeline database exists) every SNOMED concept used for admissions/conditions has a row. Writes
reference/icd10cm_codes_used.csv: the official descriptions for just the codes we use, so the repo does
not need the 14 MB source file.
"""
import csv
import sys
from collections import Counter
from pathlib import Path

import duckdb

HERE = Path(__file__).parent
CROSSWALK = HERE / "snomed_to_icd10cm.csv"
USED = HERE / "icd10cm_codes_used.csv"
DB = HERE.parent / "data" / "healthcare.duckdb"
MATCHES = {"E", "B", "N", "S", "X"}


def parse_order_file(path: Path) -> dict[str, tuple[bool, str]]:
    """CMS fixed-width order file: order(5) code(7) billable(1) short(60) long(rest)."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        code, billable, long_desc = line[6:13].strip(), line[14:15], line[77:].strip()
        out[code] = (billable == "1", long_desc)
    return out


def dotted(code: str) -> str:
    return code if len(code) <= 3 else code[:3] + "." + code[3:]


def main(order_file: str) -> int:
    official = parse_order_file(Path(order_file))
    rows = list(csv.DictReader(CROSSWALK.open(encoding="utf-8")))
    problems = []

    dup = [k for k, n in Counter(r["snomed_code"] for r in rows).items() if n > 1]
    problems += [f"duplicate snomed_code {k}" for k in dup]
    for r in rows:
        s, code, m = r["snomed_code"], r["icd10cm_code"], r["match"]
        if m not in MATCHES:
            problems.append(f"{s}: bad match '{m}'")
        if (m == "X") != (code == ""):
            problems.append(f"{s}: match X must have an empty code (and vice versa)")
        if code:
            key = code.replace(".", "")
            if key not in official:
                problems.append(f"{s}: {code} is not in the official ICD-10-CM list")
            elif not official[key][0]:
                problems.append(f"{s}: {code} exists but is a non-billable header, not a leaf code")

    if DB.exists():
        con = duckdb.connect(str(DB), read_only=True)
        need = {r[0] for r in con.execute(
            "select condition_code from condition_groups union select reason_code from admissions "
            "where reason_code is not null").fetchall()}
        have = {r["snomed_code"] for r in rows}
        problems += [f"data uses SNOMED {c} with no crosswalk row" for c in sorted(need - have)]
        extra = have - need
        if extra:
            print(f"note: {len(extra)} crosswalk rows are not used by the current data")

    if problems:
        print("\n".join(problems))
        print(f"\n{len(problems)} problem(s)")
        return 1

    used = sorted({r["icd10cm_code"] for r in rows if r["icd10cm_code"]})
    with USED.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["icd10cm_code", "description"])
        for c in used:
            w.writerow([c, official[c.replace(".", "")][1]])
    print(f"OK: {len(rows)} SNOMED concepts, {len(used)} distinct ICD-10-CM codes, all valid billable leaf codes.")
    print("match types:", dict(Counter(r["match"] for r in rows)))
    print("confidence:", dict(Counter(r["confidence"] for r in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
