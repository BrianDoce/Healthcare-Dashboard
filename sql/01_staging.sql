-- Staging: type-cast, dedupe, and drop direct identifiers (name, SSN, address, etc.).
-- Raw tables are all-varchar so messy values never break the load; try_cast turns bad values into NULL.

create or replace table stg_patients as
select
    Id                                   as patient_id,
    try_cast(BIRTHDATE as date)          as birth_date,
    try_cast(DEATHDATE as date)          as death_date,
    nullif(trim(GENDER), '')             as gender,
    nullif(trim(RACE), '')               as race,
    nullif(trim(ETHNICITY), '')          as ethnicity,
    nullif(trim(STATE), '')              as state,
    nullif(trim(COUNTY), '')             as county,
    try_cast(INCOME as integer)          as income
from raw_patients
qualify row_number() over (partition by Id order by BIRTHDATE) = 1;

create or replace table stg_organizations as
select
    Id                          as organization_id,
    trim(NAME)                  as facility_name,
    nullif(trim(CITY), '')      as city,
    nullif(trim(STATE), '')     as state
from raw_organizations
qualify row_number() over (partition by Id order by NAME) = 1;

create or replace table stg_payers as
select Id as payer_id, trim(NAME) as payer_name
from raw_payers
qualify row_number() over (partition by Id order by NAME) = 1;

create or replace table stg_encounters as
select
    Id                                                        as encounter_id,
    try_cast(START as timestamptz) at time zone 'UTC'         as start_ts,
    try_cast(STOP  as timestamptz) at time zone 'UTC'         as stop_ts,
    PATIENT                                                   as patient_id,
    ORGANIZATION                                              as organization_id,
    PAYER                                                     as payer_id,
    lower(trim(ENCOUNTERCLASS))                               as encounter_class,
    CODE                                                      as encounter_code,
    DESCRIPTION                                               as encounter_description,
    try_cast(TOTAL_CLAIM_COST as decimal(12,2))               as total_claim_cost,
    try_cast(PAYER_COVERAGE as decimal(12,2))                 as payer_coverage,
    nullif(REASONCODE, '')                                    as reason_code,
    nullif(REASONDESCRIPTION, '')                             as reason_description
from raw_encounters
qualify row_number() over (partition by Id order by START) = 1;

create or replace table stg_conditions as
select
    try_cast(START as date)     as onset_date,
    try_cast(STOP as date)      as resolved_date,
    PATIENT                     as patient_id,
    ENCOUNTER                   as encounter_id,
    CODE                        as condition_code,
    SYSTEM                      as code_system,
    DESCRIPTION                 as condition_description
from raw_conditions;

-- ICD-10-CM reference: analyst-assigned SNOMED -> ICD-10-CM crosswalk (reference/snomed_to_icd10cm.csv),
-- validated against the official CMS FY2027 code list by reference/build_icd10_reference.py.
-- Synthea itself only emits SNOMED; ICD-10 here is NOT original coding. match_type: E equivalent,
-- B ICD-10 broader than SNOMED, N default detail assumed, S status/encounter code, X no equivalent.
create or replace table dim_icd10_crosswalk as
select
    snomed_code, icd10_code, icd10_description,
    left(replace(icd10_code, '.', ''), 3) as icd10_category,
    case
        when L in ('A', 'B')                 then 'Certain infectious and parasitic diseases'
        when L = 'C' or (L = 'D' and n <= 49) then 'Neoplasms'
        when L = 'D'                         then 'Diseases of the blood and blood-forming organs and certain disorders involving the immune mechanism'
        when L = 'E'                         then 'Endocrine, nutritional and metabolic diseases'
        when L = 'F'                         then 'Mental, behavioral and neurodevelopmental disorders'
        when L = 'G'                         then 'Diseases of the nervous system'
        when L = 'H' and n <= 59             then 'Diseases of the eye and adnexa'
        when L = 'H'                         then 'Diseases of the ear and mastoid process'
        when L = 'I'                         then 'Diseases of the circulatory system'
        when L = 'J'                         then 'Diseases of the respiratory system'
        when L = 'K'                         then 'Diseases of the digestive system'
        when L = 'L'                         then 'Diseases of the skin and subcutaneous tissue'
        when L = 'M'                         then 'Diseases of the musculoskeletal system and connective tissue'
        when L = 'N'                         then 'Diseases of the genitourinary system'
        when L = 'O'                         then 'Pregnancy, childbirth and the puerperium'
        when L = 'P'                         then 'Certain conditions originating in the perinatal period'
        when L = 'Q'                         then 'Congenital malformations, deformations and chromosomal abnormalities'
        when L = 'R'                         then 'Symptoms, signs and abnormal clinical and laboratory findings, not elsewhere classified'
        when L in ('S', 'T')                 then 'Injury, poisoning and certain other consequences of external causes'
        when L = 'U'                         then 'Codes for special purposes'
        when L in ('V', 'W', 'X', 'Y')       then 'External causes of morbidity'
        when L = 'Z'                         then 'Factors influencing health status and contact with health services'
    end as icd10_chapter,
    match_type, confidence, note
from (
    select
        x.snomed_code,
        nullif(x.icd10cm_code, '')              as icd10_code,
        c.description                           as icd10_description,
        substr(nullif(x.icd10cm_code, ''), 1, 1)                      as L,
        try_cast(substr(nullif(x.icd10cm_code, ''), 2, 2) as integer) as n,
        x."match"                               as match_type,
        x.confidence,
        nullif(x.note, '')                      as note
    from raw_icd10_crosswalk x
    left join raw_icd10_codes c on c.icd10cm_code = x.icd10cm_code
);
