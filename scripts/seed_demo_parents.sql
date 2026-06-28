-- Seed démo : rattache un tuteur (avec téléphone d'urgence) à chaque élève
-- qui n'en a pas encore. Rend la liste de classe PDF crédible (colonne
-- « Tél. parent urgence » remplie au lieu de « — »).
--
-- À exécuter sur la DB du tenant démo uniquement :
--   mysql --default-character-set=utf8mb4 -u <user> -p <tenant_db> < scripts/seed_demo_parents.sql
--
-- Idempotent : ne crée un tuteur que pour les élèves sans aucun parent lié,
-- et ne recrée jamais de lien existant.

-- 1. Un tuteur par élève orphelin de parent (email encode l'id élève pour le join).
INSERT INTO parents (first_name, last_name, phone, email, created_at, updated_at)
SELECT
    'Tuteur',
    s.last_name,
    CONCAT('+225 07 ', LPAD(s.id, 2, '0'), ' 12 34 ', LPAD(s.id, 2, '0')),
    CONCAT('tuteur.s', s.id, '@demo.klassci.ci'),
    NOW(),
    NOW()
FROM students s
WHERE NOT EXISTS (
    SELECT 1 FROM parent_students ps WHERE ps.student_id = s.id
);

-- 2. Lien parent ↔ élève (récupère l'id élève depuis l'email du tuteur démo).
INSERT INTO parent_students (parent_id, student_id, relationship_type)
SELECT
    p.id,
    CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(p.email, '@', 1), 's', -1) AS UNSIGNED),
    'guardian'
FROM parents p
WHERE p.email LIKE 'tuteur.s%@demo.klassci.ci'
  AND NOT EXISTS (
      SELECT 1 FROM parent_students ps WHERE ps.parent_id = p.id
  );
