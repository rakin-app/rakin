-- Every gym's members who are minors, by birth date on the gym's today, with no
-- guardian there and still at the gym: "Falta apoderado" (#368). Since #368 nothing is
-- sent to them, and the gym sees each on Hoy and on their ficha; this tells the
-- operator which gyms to ask to add one. It prints ids and counts, never names: the gym
-- reads those in Rakin. Read only.
--
--   docker compose exec -T postgres psql -U rakin rakin < deploy/minors-without-guardian.sql
--
-- The age is app.domain.dates.AGE_OF_MAJORITY, as app.contacts.missing_guardian reads it.
SELECT g.slug, gp.person_id, count(*) OVER (PARTITION BY g.id) AS in_gym
FROM gym_person gp
JOIN gym g ON g.id = gp.gym_id
WHERE gp.left_on IS NULL
  AND gp.dob IS NOT NULL
  AND (gp.dob + interval '18 years')::date > (now() AT TIME ZONE g.timezone)::date
  AND NOT EXISTS (
      SELECT FROM guardian_link d
      WHERE d.gym_id = gp.gym_id AND d.dependent_person_id = gp.person_id
  )
ORDER BY g.slug, gp.person_id;
