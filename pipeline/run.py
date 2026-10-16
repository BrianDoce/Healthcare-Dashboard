"""Healthcare pipeline: raw Synthea CSVs -> DuckDB (staging, marts) -> data-quality report -> exports.

Usage:  python -m pipeline.run [--raw data/raw] [--db data/healthcare.duckdb] [--export exports]
"""
import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
RAW_TABLES = ["patients", "encounters", "conditions", "organizations", "payers"]
# Tables handed to Power BI / Tableau / anyone who wants flat files.
EXPORT_TABLES = ["dim_patient", "dim_facility", "admissions", "readmissions_30d", "condition_groups",
                 "dim_icd10_crosswalk"]
REFERENCE_DIR = ROOT / "reference"
REFERENCE_TABLES = {"icd10_crosswalk": "snomed_to_icd10cm.csv", "icd10_codes": "icd10cm_codes_used.csv"}


def ingest(con, raw_dir: Path) -> None:
    """Load each CSV as all-varchar so malformed values can't fail the load."""
    sources = {name: raw_dir / f"{name}.csv" for name in RAW_TABLES}
    sources.update({name: REFERENCE_DIR / fname for name, fname in REFERENCE_TABLES.items()})
    for name, path in sources.items():
        con.execute(
            f"create or replace table raw_{name} as "
            f"select * from read_csv(?, all_varchar=true, header=true)",
            [str(path)],
        )


def transform(con) -> None:
    for sql_file in sorted(SQL_DIR.glob("0*.sql")):
        con.execute(sql_file.read_text())


def data_quality(con) -> list[tuple[str, int, str]]:
    """Return (check, failing_rows, status). Failures are reported, not hidden."""
    checks = {
        "duplicate patient ids in raw":
            "select count(*) - count(distinct Id) from raw_patients",
        "duplicate encounter ids in raw":
            "select count(*) - count(distinct Id) from raw_encounters",
        "encounters with unparseable start date":
            "select count(*) from raw_encounters where try_cast(START as timestamptz) is null",
        "encounters with stop before start":
            "select count(*) from stg_encounters where stop_ts < start_ts",
        "encounters with no matching patient":
            "select count(*) from stg_encounters e anti join stg_patients p using (patient_id)",
        "inpatient encounters excluded from admissions":
            "select (select count(*) from stg_encounters where encounter_class = 'inpatient')"
            " - (select count(*) from admissions)",
        "conditions with no matching encounter":
            "select count(*) from stg_conditions c anti join stg_encounters e using (encounter_id)",
        "admissions whose SNOMED reason has no crosswalk row":
            "select count(*) from admissions a where a.reason_code is not null"
            " and not exists (select 1 from dim_icd10_crosswalk x where x.snomed_code = a.reason_code)",
        "admissions with a reason but no ICD-10 code (match X)":
            "select count(*) from admissions where reason_code is not null and icd10_code is null",
        "disorder conditions with no crosswalk row":
            "select count(*) from condition_groups where icd10_match is null",
    }
    return [(n, (v := con.execute(q).fetchone()[0]), "OK" if v == 0 else "REVIEW")
            for n, q in checks.items()]


def export(con, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for t in EXPORT_TABLES:
        con.execute(f"copy {t} to '{(out_dir / (t + '.parquet')).as_posix()}' (format parquet)")
        con.execute(f"copy {t} to '{(out_dir / (t + '.csv')).as_posix()}' (header, delimiter ',')")


BI_TABLES = ["dim_date", "dim_patient", "dim_facility", "dim_icd10", "fact_admissions", "fact_chronic_conditions"]


def export_powerbi(con, out_dir: Path) -> None:
    """Star-schema CSVs for Power BI (Get Data > Folder or Text/CSV). Booleans are already 1/0."""
    out_dir = out_dir / "powerbi"
    out_dir.mkdir(parents=True, exist_ok=True)
    for t in BI_TABLES:
        con.execute(f"copy bi.{t} to '{(out_dir / (t + '.csv')).as_posix()}' (header, delimiter ',')")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "healthcare.duckdb")
    ap.add_argument("--export", type=Path, default=ROOT / "exports")
    args = ap.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.db))
    ingest(con, args.raw)
    transform(con)
    print("Data-quality report")
    for name, n, status in data_quality(con):
        print(f"  [{status:6}] {name}: {n}")
    export(con, args.export)
    export_powerbi(con, args.export)
    for t in ["admissions", "readmissions_30d"]:
        print(f"  {t}: {con.execute(f'select count(*) from {t}').fetchone()[0]} rows")
    con.close()


if __name__ == "__main__":
    main()
