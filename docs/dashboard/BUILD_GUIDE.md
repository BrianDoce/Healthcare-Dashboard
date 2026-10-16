# Power BI build guide (about 60-90 minutes)

Goal: a 3-page dashboard that answers *which conditions drive utilization, which patients come back, and who has
chronic disease*, built on synthetic data. Built on the star schema in `exports/powerbi/`.

**Before you start:** run `python -m pipeline.run` (creates `exports/powerbi/*.csv`) and
`python scripts/dashboard_expected_values.py` (creates the known-good numbers you will check against).

## 1. Load the data (10 min)
1. Power BI Desktop > **Get data > Text/CSV**, load all six files from `exports/powerbi/`:
   `fact_admissions`, `fact_chronic_conditions`, `dim_date`, `dim_patient`, `dim_facility`, `dim_icd10`.
   Use **Transform data** (not Load) so you can set types.
2. In Power Query set types (Power BI usually guesses; verify):
   - Dates: `dim_date[date]`, `fact_admissions[admit_date]`, `fact_admissions[discharge_date]`,
     `dim_patient[birth_date]`, `fact_chronic_conditions[first_onset_date]` -> **Date**.
   - Whole numbers: all `year/quarter/month_num/..._sort`, `length_of_stay_days`, `age_at_admission`, `has_*`,
     `chronic_condition_count`, `is_index_admission`, `readmitted_30d`, `died_during_stay`, `is_deceased`.
   - `total_claim_cost` -> **Fixed decimal number**.
3. **Close & Apply.**

## 2. Model (10 min) — Model view
Create these relationships (all **many-to-one, single direction**, the "one" side is the dimension):

| From (many) | To (one) |
|---|---|
| `fact_admissions[admit_date]` | `dim_date[date]` |
| `fact_admissions[patient_id]` | `dim_patient[patient_id]` |
| `fact_admissions[facility_key]` | `dim_facility[facility_key]` |
| `fact_admissions[icd10_code]` | `dim_icd10[icd10_code]` |
| `fact_chronic_conditions[patient_id]` | `dim_patient[patient_id]` |

Then: right-click `dim_date` > **Mark as date table** (column `date`). **Sort by column:** `month_name` by `month_num`;
`year_quarter` by `year_quarter_sort`. Hide key columns you won't use as fields (the ids, `*_sort`, `*_key`).
Do not turn on bidirectional filtering; the prevalence measure depends on single direction (see `measures.dax`).

## 3. Measures (10 min)
Create a `_Measures` table and paste in `measures.dax` one measure at a time (Power BI parses each separately).
**Verify before charting:** put `Admissions`, `Unique Patients`, `Avg Length of Stay`, `Total Claim Cost`,
`Index Admissions`, `Readmissions 30d`, `30-Day Readmission Rate` in a card/table with no filters and compare with
section 1 of `expected_values.md`. Then add a Year slicer set to 2015-2025 and compare to the second KPI table.
If a number is off, fix the model first; do not "tune" the visual.

## 4. Pages

**Design rules:** one accent colour plus greys; the accent means "readmission" everywhere. Sentence-style titles that
state the finding. No pie charts; sort bars descending; format rates as `0.0%`; label axes in plain English;
turn off gridlines you don't need. Put a small text box on every page: *"Synthetic data (Synthea). Rates are simulator artifacts, not real-world benchmarks."*
Default the **Year** slicer to 2015-2025 (2026 is a partial year; earlier decades are sparse).

### Page 1 — Utilization: "Where do admissions and cost come from?"
- Cards: `Admissions`, `Unique Patients`, `Avg Length of Stay`, `Total Claim Cost`.
- Bar: `Admissions` by `dim_icd10[icd10_chapter]` (sorted desc). Title idea: *"Neoplasms are ~39% of all admissions"* (verify against the table).
- Line: `Admissions` by `dim_date[year]`.
- Bar: `Avg Cost per Admission` by `fact_admissions[age_group]`.
- Slicers: Year, `dim_facility[facility_name]`, `dim_patient[gender]`.
- Decomposition tree (optional): `Total Claim Cost` explained by chapter > ICD-10 category > code.

### Page 2 — Readmissions: "Who comes back within 30 days?"
- Cards: `30-Day Readmission Rate`, `Readmissions 30d`, `Index Admissions`.
- Bar: `Rate (min volume)` by `icd10_chapter`, with `Overall Readmission Rate` as a reference line/second series.
- Column: `30-Day Readmission Rate` by `age_group` (expect low under 45, ~30% for 45-64).
- Line: rate by `dim_date[year_quarter]` (hide quarters with tiny volume or smooth by year).
- Table: `icd10_code`, `icd10_description`, `Index Admissions`, `Rate (min volume)`, `Share of Readmissions`
  sorted by `Share of Readmissions`. Conditional-format the rate column (data bars).
- Annotation text box: *"Lung-cancer treatment cycles generate most simulated readmissions; this is a Synthea artifact."*
- Drill-through page or tooltip page: facility detail.

### Page 3 — Chronic conditions: "Who has chronic disease?"
- Cards: `Patients`, `Comorbidity %`.
- Bar: `Prevalence %` by `fact_chronic_conditions[chronic_group]`.
- Matrix (heatmap via conditional formatting): rows `dim_patient[age_band]`, columns `chronic_group`, values `Prevalence %`.
- Map (Filled map) or bar: `Prevalence %` by `dim_patient[county_state]`; slicer for `chronic_group` (use the field from
  `fact_chronic_conditions`; because of single-direction filtering, set the map to show `Patients With Condition` if you
  slice by group on this page).
- Slicers: `age_band`, `gender`, `county`.
- Footer note on method: *"Chronic groups are defined from analyst-assigned ICD-10-CM categories; see README."*

## 5. Finish and share
- Check every page against `expected_values.md` once more with slicers cleared.
- **Accessibility:** alt text on visuals, colour-blind-safe palette, tab order sensible.
- **Export:** File > Export > PDF, and take clean screenshots per page for the README and your portfolio.
- **Sharing:** the free tier has no public link. Options: (a) PDF + screenshots in the repo, (b) commit the `.pbix`
  (it contains only synthetic data), (c) a short screen recording, (d) republish the same model to Tableau Public if you
  need a live link. Do not "Publish to web" from a work account.
- Save the `.pbix` in `dashboard/` and add a section to the README with the screenshots.

## 6. What to be ready to explain in an interview
- Why a star schema, and why every relationship is one-to-many with single-direction filtering.
- How `Prevalence %` gets its denominator, and why `ALLSELECTED()` is used for the benchmark.
- Why rates are blanked below 30 index admissions.
- That ICD-10 here is an analyst-built crosswalk (53% of admissions are on a "broader" mapping), and that the data is synthetic.
