-- Fix accents on subject names. Run once locally.
-- Encoding: UTF-8 (without BOM). Execute via:
--   mysql --default-character-set=utf8mb4 -u root local < update_subject_accents.sql
SET NAMES utf8mb4;

UPDATE subjects SET name = 'Mathématiques'                  WHERE name = 'Mathematiques';
UPDATE subjects SET name = 'Français'                       WHERE name = 'Francais';
UPDATE subjects SET name = 'Histoire-Géographie'            WHERE name = 'Histoire-Geographie';
UPDATE subjects SET name = 'Éducation Civique et Morale'    WHERE name = 'Education Civique et Morale';
UPDATE subjects SET name = 'Éducation Physique et Sportive' WHERE name = 'Education Physique et Sportive';

SELECT name, COUNT(*) AS n FROM subjects GROUP BY name ORDER BY name;
