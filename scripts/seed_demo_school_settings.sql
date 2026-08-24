-- Seed des paramètres d'établissement pour le tenant DÉMO (Collège Moderne
-- Saint-Augustin). Donne aux PDF de démonstration une identité crédible :
-- nom réel, code MENA, contacts, devise, chef d'établissement (nom ET titre
-- distincts), et des couleurs propres à l'école (maroon + or) pour démontrer
-- que le thème PDF vient des settings du tenant, pas des couleurs KLASSCI.
--
-- À exécuter sur la DB du tenant démo uniquement :
--   mysql --default-character-set=utf8mb4 -u <user> -p <tenant_db> < scripts/seed_demo_school_settings.sql
--
-- Idempotent (UPDATE du singleton school_settings).

UPDATE school_settings SET
  school_name      = 'Collège Moderne Saint-Augustin',
  ministry_code    = 'DRENA-ABJ4-0142',
  address          = 'Cocody Riviera 3, Abidjan — Côte d''Ivoire',
  phone            = '+225 27 22 44 55 66',
  email            = 'secretariat@saint-augustin.ci',
  website          = 'www.saint-augustin.ci',
  motto            = 'Science, Conscience, Excellence',
  head_master_name = 'Dr. KOUASSI Bernard',
  head_master_title= 'Le Proviseur',
  primary_color    = '#7F1D1D',
  accent_color     = '#B45309';
