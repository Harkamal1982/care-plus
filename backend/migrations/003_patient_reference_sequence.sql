
CREATE SEQUENCE IF NOT EXISTS patient_ref_seq;

SELECT setval(
    'patient_ref_seq',
    COALESCE(
        (
            SELECT MAX(
                CAST(SUBSTRING(patient_ref FROM 5) AS BIGINT)
            )
            FROM patients
            WHERE patient_ref ~ '^PAT-[0-9]+$'
        ),
        0
    ) + 1,
    false
);
