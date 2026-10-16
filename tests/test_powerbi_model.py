"""Integrity tests for the Power BI star schema (schema `bi`). Run against the built database."""
from pathlib import Path

import duckdb
import pytest

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "healthcare.duckdb"

pytestmark = pytest.mark.skipif(not Path(DEFAULT_DB).exists(), reason="run the pipeline first")


@pytest.fixture(scope="module")
def con():
    return duckdb.connect(str(DEFAULT_DB), read_only=True)


def one(con, sql):
    return con.execute(sql).fetchone()[0]


@pytest.mark.parametrize("table,key", [
    ("dim_date", "date"), ("dim_patient", "patient_id"), ("dim_facility", "facility_key"),
    ("dim_icd10", "icd10_code"), ("fact_admissions", "encounter_id")])
def test_keys_are_unique_and_not_null(con, table, key):
    assert one(con, f"select count(*) - count(distinct {key}) from bi.{table}") == 0
    assert one(con, f"select count(*) from bi.{table} where {key} is null") == 0


@pytest.mark.parametrize("fk,dim,dkey", [
    ("patient_id", "dim_patient", "patient_id"), ("facility_key", "dim_facility", "facility_key"),
    ("admit_date", "dim_date", "date"), ("icd10_code", "dim_icd10", "icd10_code")])
def test_every_fact_row_joins_to_its_dimension(con, fk, dim, dkey):
    orphans = one(con, f"select count(*) from bi.fact_admissions f anti join bi.{dim} d on f.{fk} = d.{dkey}")
    assert orphans == 0, f"{orphans} admissions have no matching {dim} row (blank rows in visuals)"


def test_chronic_facts_join_to_patients(con):
    assert one(con, "select count(*) from bi.fact_chronic_conditions f anti join bi.dim_patient d using (patient_id)") == 0
    assert one(con, "select count(*) - count(distinct (patient_id, chronic_group)) from bi.fact_chronic_conditions") == 0


def test_flags_are_zero_one_and_readmission_null_only_for_non_index(con):
    assert one(con, "select count(*) from bi.fact_admissions where is_index_admission not in (0,1) "
                    "or died_during_stay not in (0,1) or readmitted_30d not in (0,1)") == 0
    assert one(con, "select count(*) from bi.fact_admissions where (is_index_admission = 0) <> (readmitted_30d is null)") == 0
    assert one(con, "select count(*) from bi.dim_patient where is_deceased not in (0,1)") == 0


def test_bi_readmission_rate_matches_the_analytic_table(con):
    bi = one(con, "select 100.0 * sum(readmitted_30d) / sum(is_index_admission) from bi.fact_admissions")
    main = one(con, "select 100.0 * avg(readmitted_30d::int) from readmissions_30d")
    assert bi == pytest.approx(main)


def test_patient_flags_agree_with_chronic_fact(con):
    pairs = {"has_diabetes": "Diabetes", "has_hypertension": "Hypertension", "has_copd": "COPD",
             "has_heart_failure": "Heart failure", "has_ckd": "Chronic kidney disease", "has_asthma": "Asthma"}
    for col, group in pairs.items():
        assert one(con, f"select sum({col}) from bi.dim_patient") == \
               one(con, f"select count(*) from bi.fact_chronic_conditions where chronic_group = '{group}'"), group
    assert one(con, "select sum(chronic_condition_count) from bi.dim_patient") == \
           one(con, "select count(*) from bi.fact_chronic_conditions")


def test_date_dimension_covers_all_dates_contiguously(con):
    assert one(con, "select count(*) from bi.fact_admissions where discharge_date > (select max(date) from bi.dim_date)") == 0
    span = one(con, "select date_diff('day', min(date), max(date)) + 1 from bi.dim_date")
    assert span == one(con, "select count(*) from bi.dim_date")


def test_no_direct_identifiers_in_bi_tables(con):
    banned = {"ssn", "first", "last", "name", "address", "drivers", "passport", "phone", "zip", "lat", "lon"}
    for t in ("dim_patient", "fact_admissions", "dim_facility"):
        cols = {r[0].lower() for r in con.execute(f"describe bi.{t}").fetchall()}
        leaked = cols & banned
        assert not leaked, f"{t}: {leaked}"
