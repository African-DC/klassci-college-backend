-- Seed 36 instances lycée (2nde A + 1ère C/D + Term A/C/D × 6 matières)
-- Coefficients basés sur le programme officiel BAC ivoirien (MENA-CI / DECO).
-- Heures hebdomadaires alignées avec le cursus francophone Afrique de l'Ouest.
--
-- Run once locally :
--   mysql --default-character-set=utf8mb4 -u root local < seed_lycee_instances.sql
--
-- Idempotence: relies on UniqueConstraint(name, level_id, series_id) already
-- enforced server-side in duplicate_subject. If you re-run, MySQL will throw
-- a duplicate-key error on the offending row — clean up via:
--   DELETE FROM subjects WHERE level_id IN (5,6,7) AND series_id IN (1,2,3,4,5,6);
SET NAMES utf8mb4;

-- IDs catalogue (level_id IS NULL) :
--   1=Mathematiques  2=Francais  3=Anglais  4=Sciences Physiques
--   5=SVT  6=Histoire-Geographie  8=EPS  11=Philosophie
-- IDs levels :  5=2nde  6=1ère  7=Terminale
-- IDs series :  1=2nde A  2=1ère C  3=1ère D  4=Term A  5=Term C  6=Term D

INSERT INTO subjects (name, coefficient, hours_per_week, level_id, series_id, teacher_id, color, created_at, updated_at) VALUES
-- 2nde A (tronc commun littéraire) — series_id=1, level_id=5
('Mathématiques',                  2, 4, 5, 1, NULL, NULL, NOW(), NOW()),
('Français',                       4, 5, 5, 1, NULL, NULL, NOW(), NOW()),
('Anglais',                        2, 3, 5, 1, NULL, NULL, NOW(), NOW()),
('Histoire-Géographie',            2, 3, 5, 1, NULL, NULL, NOW(), NOW()),
('Sciences de la Vie et de la Terre', 2, 3, 5, 1, NULL, NULL, NOW(), NOW()),
('Éducation Physique et Sportive', 1, 2, 5, 1, NULL, NULL, NOW(), NOW()),

-- 1ère C (sciences-maths) — series_id=2, level_id=6
('Mathématiques',                  5, 7, 6, 2, NULL, NULL, NOW(), NOW()),
('Sciences Physiques',             5, 5, 6, 2, NULL, NULL, NOW(), NOW()),
('Sciences de la Vie et de la Terre', 3, 2, 6, 2, NULL, NULL, NOW(), NOW()),
('Français',                       4, 4, 6, 2, NULL, NULL, NOW(), NOW()),
('Anglais',                        3, 3, 6, 2, NULL, NULL, NOW(), NOW()),
('Histoire-Géographie',            3, 3, 6, 2, NULL, NULL, NOW(), NOW()),

-- 1ère D (sciences-SVT) — series_id=3, level_id=6
('Mathématiques',                  4, 5, 6, 3, NULL, NULL, NOW(), NOW()),
('Sciences de la Vie et de la Terre', 6, 4, 6, 3, NULL, NULL, NOW(), NOW()),
('Sciences Physiques',             4, 4, 6, 3, NULL, NULL, NOW(), NOW()),
('Français',                       4, 4, 6, 3, NULL, NULL, NOW(), NOW()),
('Anglais',                        3, 3, 6, 3, NULL, NULL, NOW(), NOW()),
('Histoire-Géographie',            3, 3, 6, 3, NULL, NULL, NOW(), NOW()),

-- Terminale A (littéraire) — series_id=4, level_id=7
('Philosophie',                    4, 8, 7, 4, NULL, NULL, NOW(), NOW()),
('Français',                       4, 4, 7, 4, NULL, NULL, NOW(), NOW()),
('Histoire-Géographie',            4, 4, 7, 4, NULL, NULL, NOW(), NOW()),
('Mathématiques',                  3, 3, 7, 4, NULL, NULL, NOW(), NOW()),
('Anglais',                        4, 4, 7, 4, NULL, NULL, NOW(), NOW()),
('Éducation Physique et Sportive', 2, 2, 7, 4, NULL, NULL, NOW(), NOW()),

-- Terminale C (sciences-maths) — series_id=5, level_id=7
('Mathématiques',                  5, 7, 7, 5, NULL, NULL, NOW(), NOW()),
('Sciences Physiques',             5, 5, 7, 5, NULL, NULL, NOW(), NOW()),
('Philosophie',                    4, 2, 7, 5, NULL, NULL, NOW(), NOW()),
('Anglais',                        3, 3, 7, 5, NULL, NULL, NOW(), NOW()),
('Histoire-Géographie',            3, 3, 7, 5, NULL, NULL, NOW(), NOW()),
('Sciences de la Vie et de la Terre', 3, 2, 7, 5, NULL, NULL, NOW(), NOW()),

-- Terminale D (sciences-SVT) — series_id=6, level_id=7
('Sciences de la Vie et de la Terre', 6, 4, 7, 6, NULL, NULL, NOW(), NOW()),
('Mathématiques',                  4, 5, 7, 6, NULL, NULL, NOW(), NOW()),
('Sciences Physiques',             4, 4, 7, 6, NULL, NULL, NOW(), NOW()),
('Philosophie',                    4, 2, 7, 6, NULL, NULL, NOW(), NOW()),
('Anglais',                        3, 3, 7, 6, NULL, NULL, NOW(), NOW()),
('Histoire-Géographie',            3, 3, 7, 6, NULL, NULL, NOW(), NOW());

-- Validation : count by (level, series) — doit retourner 6 lignes × 6 matières
SELECT level_id, series_id, COUNT(*) AS instances_count, SUM(coefficient) AS total_coef, SUM(hours_per_week) AS total_hours
FROM subjects
WHERE level_id IN (5,6,7) AND series_id IS NOT NULL
GROUP BY level_id, series_id
ORDER BY level_id, series_id;
