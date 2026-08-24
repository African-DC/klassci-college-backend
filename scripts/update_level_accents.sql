-- Fix accents on level names. Run once locally.
-- Encoding: UTF-8 (without BOM). Execute via:
--   mysql --default-character-set=utf8mb4 -u root local < update_level_accents.sql
SET NAMES utf8mb4;

UPDATE levels SET name = '6ème'      WHERE id = 1;
UPDATE levels SET name = '5ème'      WHERE id = 2;
UPDATE levels SET name = '4ème'      WHERE id = 3;
UPDATE levels SET name = '3ème'      WHERE id = 4;
UPDATE levels SET name = '2nde'      WHERE id = 5;
UPDATE levels SET name = '1ère'      WHERE id = 6;
UPDATE levels SET name = 'Terminale' WHERE id = 7;

SELECT id, name, `order` FROM levels ORDER BY `order`;
