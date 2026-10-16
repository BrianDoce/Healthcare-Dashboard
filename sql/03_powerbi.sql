-- Star schema for the Power BI dashboard (schema `bi`). Flat, typed, BI-friendly:
--   * booleans exported as 1/0 so Power Query never has to guess a type
--   * one-row-per-key dimensions, so every relationship is a clean one-to-many
--   * no names, addresses, or other direct identifiers (patient_id is a synthetic key)
create schema if not exists bi;

create or replace table bi.dim_date as
select
    d::date                                         as date,
    extract(year from d)::int                       as year,
    extract(quarter from d)::int                    as quarter,
    extract(month from d)::int                      as month_num,
    strftime(d, '%b')                               as month_name,
    extract(year from d)::int || '-Q' || extract(quarter from d)::int as year_quarter,
    extract(year from d)::int * 10 + extract(quarter from d)::int      as year_quarter_sort,
    strftime(d, '%Y-%m')                            as year_month
from generate_series(
    (select date_trunc('year', min(admit_ts))::date from admissions),
    (select (date_trunc('year', max(admit_ts)) + interval '1 year' - interval '1 day')::date from admissions),
    interval '1 day') as t(d);

create or replace table bi.dim_facility as
select organization_id as facility_key, facility_name, city, state from dim_facility;

-- One row per distinct ICD-10-CM code used by the data (the crosswalk maps many SNOMED concepts to one code).
create or replace table bi.dim_icd10 as
select
    icd10_code,
    any_value(icd10_description)                    as icd10_description,
    any_value(icd10_category)                       as icd10_category,
    any_value(icd10_chapter)                        as icd10_chapter,
    -- weakest fidelity wins when several SNOMED concepts share a code: X < B < N < S < E
    case min(case match_type when 'X' then 0 when 'B' then 1 when 'N' then 2 when 'S' then 3 else 4 end)
        when 0 then 'X' when 1 then 'B' when 2 then 'N' when 3 then 'S' else 'E' end as weakest_match
from dim_icd10_crosswalk
where icd10_code is not null
group by icd10_code;

-- Patient dimension with chronic-condition flags and age as of the end of the data (or death).
create or replace table bi.dim_patient as
with data_end as (select max(admit_ts)::date as d from admissions),
flags as (
    select patient_id,
        max((chronic_group = 'Diabetes')::int)               as has_diabetes,
        max((chronic_group = 'Hypertension')::int)           as has_hypertension,
        max((chronic_group = 'COPD')::int)                   as has_copd,
        max((chronic_group = 'Heart failure')::int)          as has_heart_failure,
        max((chronic_group = 'Chronic kidney disease')::int) as has_ckd,
        max((chronic_group = 'Asthma')::int)                 as has_asthma
    from condition_groups
    where chronic_group is not null
    group by patient_id
)
select
    p.patient_id, p.gender, p.race, p.ethnicity, p.state, p.county,
    p.county || ', ' || p.state                                  as county_state,
    p.birth_date, p.is_deceased::int as is_deceased,
    date_diff('year', p.birth_date, coalesce(p.death_date, (select d from data_end))) as age_as_of,
    case
        when date_diff('year', p.birth_date, coalesce(p.death_date, (select d from data_end))) < 18 then '0-17'
        when date_diff('year', p.birth_date, coalesce(p.death_date, (select d from data_end))) < 45 then '18-44'
        when date_diff('year', p.birth_date, coalesce(p.death_date, (select d from data_end))) < 65 then '45-64'
        when date_diff('year', p.birth_date, coalesce(p.death_date, (select d from data_end))) < 80 then '65-79'
        else '80+'
    end                                                          as age_band,
    coalesce(f.has_diabetes, 0) as has_diabetes, coalesce(f.has_hypertension, 0) as has_hypertension,
    coalesce(f.has_copd, 0) as has_copd, coalesce(f.has_heart_failure, 0) as has_heart_failure,
    coalesce(f.has_ckd, 0) as has_ckd, coalesce(f.has_asthma, 0) as has_asthma,
    coalesce(f.has_diabetes, 0) + coalesce(f.has_hypertension, 0) + coalesce(f.has_copd, 0)
      + coalesce(f.has_heart_failure, 0) + coalesce(f.has_ckd, 0) + coalesce(f.has_asthma, 0)
                                                                 as chronic_condition_count
from dim_patient p
left join flags f using (patient_id);

-- Admission grain. is_index_admission / readmitted_30d follow the CMS-style definition used everywhere else:
-- admissions ending in in-hospital death are not index admissions, and readmitted_30d is NULL for them.
create or replace table bi.fact_admissions as
select
    a.encounter_id,
    a.patient_id,
    a.organization_id                              as facility_key,
    a.admit_ts::date                               as admit_date,
    a.discharge_ts::date                           as discharge_date,
    a.length_of_stay_days,
    a.age_at_admission,
    a.age_group,
    a.icd10_code,
    a.icd10_category,
    a.icd10_chapter,
    a.icd10_match,
    a.principal_reason,
    a.total_claim_cost,
    a.died_during_stay::int                        as died_during_stay,
    (r.encounter_id is not null)::int              as is_index_admission,
    r.readmitted_30d::int                          as readmitted_30d,
    r.days_to_next_admit
from admissions a
left join readmissions_30d r using (encounter_id);

-- One row per patient x chronic condition group.
create or replace table bi.fact_chronic_conditions as
select patient_id, chronic_group, min(onset_date) as first_onset_date
from condition_groups
where chronic_group is not null
group by patient_id, chronic_group;
