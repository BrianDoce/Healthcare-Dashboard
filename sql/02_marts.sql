-- Analytic layer: this is what the dashboard and the NL->SQL agent query.

create or replace table dim_patient as
select
    patient_id, gender, race, ethnicity, state, county, income, birth_date, death_date,
    death_date is not null as is_deceased
from stg_patients;

create or replace table dim_facility as
select organization_id, facility_name, city, state from stg_organizations;

-- One row per inpatient admission. Rows with a missing or inverted stay window are excluded here
-- and counted in the data-quality report instead of silently distorting length of stay.
create or replace table admissions as
select
    e.encounter_id,
    e.patient_id,
    e.organization_id,
    e.payer_id,
    e.start_ts                                              as admit_ts,
    e.stop_ts                                               as discharge_ts,
    date_diff('day', e.start_ts::date, e.stop_ts::date)     as length_of_stay_days,
    date_diff('year', p.birth_date, e.start_ts::date)       as age_at_admission,
    case
        when date_diff('year', p.birth_date, e.start_ts::date) < 18 then '0-17'
        when date_diff('year', p.birth_date, e.start_ts::date) < 45 then '18-44'
        when date_diff('year', p.birth_date, e.start_ts::date) < 65 then '45-64'
        when date_diff('year', p.birth_date, e.start_ts::date) < 80 then '65-79'
        else '80+'
    end                                                     as age_group,
    e.reason_code,
    coalesce(e.reason_description, 'Unspecified')           as principal_reason,
    x.icd10_code,
    x.icd10_description,
    x.icd10_category,
    x.icd10_chapter,
    x.match_type                                            as icd10_match,
    e.total_claim_cost,
    (p.death_date is not null
        and p.death_date between e.start_ts::date and e.stop_ts::date) as died_during_stay
from stg_encounters e
join stg_patients p using (patient_id)
left join dim_icd10_crosswalk x on x.snomed_code = e.reason_code
where e.encounter_class = 'inpatient'
  and e.start_ts is not null
  and e.stop_ts is not null
  and e.stop_ts >= e.start_ts;

-- Readmission logic: look at each patient's next admission (LEAD). The index admission is
-- "readmitted" if the next admission starts 0-30 days after the index discharge.
-- Index admissions where the patient died in hospital are not eligible (CMS-style exclusion).
create or replace table readmissions_30d as
with sequenced as (
    select
        a.*,
        lead(admit_ts) over w as next_admit_ts,
        lead(encounter_id) over w as next_encounter_id
    from admissions a
    window w as (partition by patient_id order by admit_ts)
)
select
    encounter_id, patient_id, organization_id, admit_ts, discharge_ts, length_of_stay_days,
    age_at_admission, age_group, principal_reason, reason_code,
    icd10_code, icd10_description, icd10_category, icd10_chapter, icd10_match, total_claim_cost,
    next_encounter_id,
    date_diff('day', discharge_ts::date, next_admit_ts::date) as days_to_next_admit,
    coalesce(date_diff('day', discharge_ts::date, next_admit_ts::date) between 0 and 30, false)
                                                              as readmitted_30d
from sequenced
where not died_during_stay;

-- Chronic-condition groups for the prevalence dashboard, defined by ICD-10-CM category (via the
-- analyst-assigned crosswalk): E08-E13 diabetes, I10-I16 hypertension, J43-J44 COPD, I50 heart failure,
-- N18 chronic kidney disease (incl. ESRD), J45 asthma.
create or replace table condition_groups as
select
    c.patient_id, c.condition_code, c.condition_description, c.onset_date,
    x.icd10_code, x.icd10_description, x.icd10_category, x.icd10_chapter, x.match_type as icd10_match,
    case
        when x.icd10_category in ('E08', 'E09', 'E10', 'E11', 'E13')            then 'Diabetes'
        when x.icd10_category in ('I10', 'I11', 'I12', 'I13', 'I15', 'I16')     then 'Hypertension'
        when x.icd10_category in ('J43', 'J44')                                 then 'COPD'
        when x.icd10_category = 'I50'                                           then 'Heart failure'
        when x.icd10_category = 'N18'                                           then 'Chronic kidney disease'
        when x.icd10_category = 'J45'                                           then 'Asthma'
    end as chronic_group
from stg_conditions c
left join dim_icd10_crosswalk x on x.snomed_code = c.condition_code
where c.condition_description ilike '%(disorder)%';
