-- Ajoute la permission grades:edit (modify existing notes) sur un tenant
-- existant et l'attribue par défaut aux rôles admin, director, teacher.
-- Idempotent grâce à INSERT IGNORE.
-- Run once locally :
--   mysql --default-character-set=utf8mb4 -u root local < add_grades_edit_permission.sql
SET NAMES utf8mb4;

INSERT IGNORE INTO permissions (slug, name)
VALUES ('grades:edit', 'Modify already-recorded grades');

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.slug = 'grades:edit'
WHERE r.name IN ('admin', 'director', 'teacher');

SELECT r.name AS role, p.slug AS perm
FROM role_permissions rp
JOIN roles r ON r.id = rp.role_id
JOIN permissions p ON p.id = rp.permission_id
WHERE p.slug LIKE 'grades:%'
ORDER BY r.name, p.slug;
