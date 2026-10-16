import duckdb
import pytest

from pipeline import run

PAT_H = "Id,BIRTHDATE,DEATHDATE,GENDER,RACE,ETHNICITY,STATE,COUNTY,INCOME"
ENC_H = ("Id,START,STOP,PATIENT,ORGANIZATION,PAYER,ENCOUNTERCLASS,CODE,DESCRIPTION,"
         "BASE_ENCOUNTER_COST,TOTAL_CLAIM_COST,PAYER_COVERAGE,REASONCODE,REASONDESCRIPTION")


def enc(i, start, stop, pat, cls="inpatient", reason="Heart failure", reason_code=""):
    return f"{i},{start},{stop},{pat},org1,pay1,{cls},1,x,0,100.00,0,{reason_code},{reason}"


@pytest.fixture
def con(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "patients.csv").write_text("\n".join([
        PAT_H,
        "p1,1950-01-01,,F,white,nonhispanic,MA,Suffolk,1000",
        "p1,1950-01-01,,F,white,nonhispanic,MA,Suffolk,1000",          # duplicate patient
        "p2,1980-05-05,2020-03-10,M,asian,nonhispanic,MA,Suffolk,2000",  # dies in stay
        "p3,1990-01-01,,F,white,nonhispanic,MA,Suffolk,3000",
    ]))
    (raw / "encounters.csv").write_text("\n".join([
        ENC_H,
        enc("e1", "2020-01-01T10:00:00Z", "2020-01-05T10:00:00Z", "p1", reason_code="88805009"),  # CHF
        enc("e2", "2020-02-04T10:00:00Z", "2020-02-08T10:00:00Z", "p1"),   # day 30 -> readmit
        enc("e3", "2020-04-01T10:00:00Z", "2020-04-03T10:00:00Z", "p1"),   # day 53 -> not
        enc("e3", "2020-04-01T10:00:00Z", "2020-04-03T10:00:00Z", "p1"),   # duplicate encounter
        enc("e4", "2020-03-01T10:00:00Z", "2020-03-12T10:00:00Z", "p2", reason_code="999999999"),  # died; unmapped
        enc("e5", "not-a-date", "2020-03-12T10:00:00Z", "p3"),             # bad start
        enc("e6", "2020-06-10T10:00:00Z", "2020-06-01T10:00:00Z", "p3"),   # stop before start
        enc("e7", "2020-01-01T10:00:00Z", "2020-01-05T10:00:00Z", "p1", cls="ambulatory"),
    ]))
    (raw / "conditions.csv").write_text("START,STOP,PATIENT,ENCOUNTER,SYSTEM,CODE,DESCRIPTION\n"
                                        "2020-01-01,,p1,e1,s,44054006,Diabetes mellitus type 2 (disorder)\n")
    (raw / "organizations.csv").write_text("Id,NAME,ADDRESS,CITY,STATE,ZIP\norg1,Gen Hosp,a,Boston,MA,1\n")
    (raw / "payers.csv").write_text("Id,NAME\npay1,Medicare\n")
    c = duckdb.connect()
    run.ingest(c, raw)
    run.transform(c)
    return c


def test_duplicates_removed(con):
    assert con.execute("select count(*) from stg_patients").fetchone()[0] == 3
    assert con.execute("select count(*) from stg_encounters where encounter_id='e3'").fetchone()[0] == 1


def test_bad_rows_excluded_from_admissions_and_reported(con):
    ids = {r[0] for r in con.execute("select encounter_id from admissions").fetchall()}
    assert ids == {"e1", "e2", "e3", "e4"}  # e5, e6 dropped; e7 not inpatient
    report = {n: v for n, v, _ in run.data_quality(con)}
    assert report["encounters with unparseable start date"] == 1
    assert report["duplicate encounter ids in raw"] == 1


def test_readmission_window_boundaries(con):
    r = dict(con.execute("select encounter_id, readmitted_30d from readmissions_30d").fetchall())
    assert r["e1"] is True    # next admit exactly 30 days after discharge
    assert r["e2"] is False   # next admit 53 days later
    assert r["e3"] is False   # no later admission


def test_in_hospital_death_excluded_from_denominator(con):
    ids = {r[0] for r in con.execute("select encounter_id from readmissions_30d").fetchall()}
    assert "e4" not in ids


def test_no_direct_identifiers_in_marts(con):
    for t in ("dim_patient", "admissions", "readmissions_30d"):
        cols = {r[0].lower() for r in con.execute(f"describe {t}").fetchall()}
        assert not cols & {"ssn", "first", "last", "address", "drivers", "passport"}


def test_chronic_group(con):
    assert con.execute("select chronic_group from condition_groups").fetchone()[0] == "Diabetes"


def test_icd10_columns_attached_to_admissions_and_readmissions(con):
    row = con.execute("select icd10_code, icd10_category, icd10_chapter, icd10_match from admissions "
                      "where encounter_id = 'e1'").fetchone()
    assert row == ("I50.9", "I50", "Diseases of the circulatory system", "B")
    assert con.execute("select icd10_code from readmissions_30d where encounter_id = 'e1'").fetchone()[0] == "I50.9"


def test_unmapped_snomed_code_is_kept_with_null_icd10(con):
    # an unknown reason code must not drop the admission; it just has no ICD-10
    assert con.execute("select icd10_code from admissions where encounter_id = 'e4'").fetchone()[0] is None
    report = {n: v for n, v, _ in run.data_quality(con)}
    assert report["admissions with a reason but no ICD-10 code (match X)"] == 1


def test_chronic_group_comes_from_icd10_category(con):
    assert con.execute("select icd10_code, chronic_group from condition_groups").fetchone() == ("E11.9", "Diabetes")


def test_crosswalk_chapters_cover_every_mapped_code(con):
    bad = con.execute("select count(*) from dim_icd10_crosswalk where icd10_code is not null "
                      "and icd10_chapter is null").fetchone()[0]
    assert bad == 0
