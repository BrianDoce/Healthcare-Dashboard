# Chronic Disease & Readmissions Dashboard (Power BI)

**Business question:** Which conditions drive hospital utilization, which patients come back within 30 days, and how
common are chronic diseases across ages and counties, using ICD-10-CM diagnosis groups?

**Status:** the data model, measures, and build guide are complete and tested. **The Power BI report (`.pbix`) is not built
yet**; the next step is following `docs/dashboard/BUILD_GUIDE.md` in Power BI Desktop (about 1-2 hours).

**Data:** [Synthea](https://synthetichealth.github.io/synthea/) synthetic patients, Massachusetts (5,733 patients, 5,670
inpatient admissions). No real PHI. Rates are simulator artifacts, not real-world benchmarks.

## What is here

| Piece | Where |
|---|---|
| Data prep: raw Synthea CSVs -> cleaned tables -> star schema | `pipeline/run.py`, `sql/` |
| Star schema for Power BI (CSV) | `exports/powerbi/` (generated; git-ignored) |
| ICD-10-CM crosswalk (SNOMED -> ICD-10-CM), validated against the CMS code list | `reference/` |
| DAX measures (17) with comments | `docs/dashboard/measures.dax` |
| Independently computed numbers to check the dashboard against | `docs/dashboard/expected_values.md` |
| Page-by-page build guide | `docs/dashboard/BUILD_GUIDE.md` |
| Tests (29): cleaning logic, crosswalk integrity, model integrity | `tests/` |

## Data model (star schema)

```
dim_date ─┐
dim_patient ──┬─► fact_admissions ◄── dim_facility
dim_icd10 ────┘            (admission grain)
dim_patient ◄── fact_chronic_conditions   (patient x chronic condition)
```
All relationships are many-to-one with single-direction filtering. Tests assert unique keys, **zero orphan rows** (no blank
categories in visuals), 1/0 flags, chronic flags consistent with the fact table, and that the BI readmission rate equals the
analytic table's.

**Readmission definition (CMS-style):** an index admission is readmitted if the same patient's next admission starts 0-30
days after discharge; admissions ending in in-hospital death are excluded from the denominator.

## Planned pages
1. **Utilization:** admissions, cost, and length of stay by ICD-10 chapter, year, age group.
2. **Readmissions:** 30-day rate by chapter, age, and quarter, with a minimum-volume rule so tiny groups don't show a 100% rate.
3. **Chronic conditions:** prevalence (diabetes, hypertension, COPD, heart failure, CKD, asthma) by age band and county; comorbidity.

## Things to know before trusting any number
- **ICD-10 here is an analyst-built crosswalk, not original coding.** Synthea only emits SNOMED. I mapped all 209 SNOMED
  concepts to 179 ICD-10-CM (FY2027) codes and validated each against the official CMS list (this caught 7 invalid codes),
  but validation shows a code *exists*, not that it is *right*. Each row is labelled equivalent / broader / default-assumed /
  status / none; **53% of admissions land on a "broader" mapping** (mostly lung cancer, where ICD-10-CM codes the site but
  not the stage). A coder should review before any real use.
- **Lung-cancer treatment cycles generate 74.5% of simulated readmissions.** That is a Synthea artifact, not a clinical finding.
- Admissions span 1922-2026; the guide recommends a 2015-2025 year slicer (2026 is a partial year).
- Chronic groups are ICD-10 categories: E08-E13, I10-I16, J43-J44, I50, N18 (includes ESRD), J45.

## Reproduce
```
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
scripts\generate_data.ps1        # needs Java 17+ and the Synthea jar; or place Synthea CSVs in data/raw/
python -m pipeline.run           # builds data/healthcare.duckdb and exports/powerbi/*.csv
python scripts/dashboard_expected_values.py
python -m pytest
```
Then follow `docs/dashboard/BUILD_GUIDE.md`.
