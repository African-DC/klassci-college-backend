"""Static catalog of all permission slugs and the role → permission matrix.

Pure data, no logic. The migration `20260509_0024_*` is the source of truth
for what gets seeded into existing tenant DBs; this module is the source of
truth for what gets seeded into NEW tenant DBs by `provisioning.seed_tenant_data`.

Keep the two in sync — `tests/test_tenant_service.py::test_role_permissions_reference_valid_slugs`
guards against drift inside this file but cannot detect missing migrations.
"""

from typing import Any

ALL_PERMISSIONS: list[dict[str, str]] = [
    # Admin module (28)
    {"slug": "admin:students:read", "name": "View students"},
    {"slug": "admin:students:create", "name": "Create students"},
    {"slug": "admin:students:update", "name": "Update students"},
    {"slug": "admin:students:delete", "name": "Delete students"},
    {"slug": "admin:teachers:read", "name": "View teachers"},
    {"slug": "admin:teachers:create", "name": "Create teachers"},
    {"slug": "admin:teachers:update", "name": "Update teachers"},
    {"slug": "admin:teachers:delete", "name": "Delete teachers"},
    {"slug": "admin:staff:read", "name": "View staff"},
    {"slug": "admin:staff:create", "name": "Create staff"},
    {"slug": "admin:staff:update", "name": "Update staff"},
    {"slug": "admin:staff:delete", "name": "Delete staff"},
    {"slug": "admin:classes:read", "name": "View classes"},
    {"slug": "admin:classes:create", "name": "Create classes"},
    {"slug": "admin:classes:update", "name": "Update classes"},
    {"slug": "admin:classes:delete", "name": "Delete classes"},
    {"slug": "admin:subjects:read", "name": "View subjects"},
    {"slug": "admin:subjects:create", "name": "Create subjects"},
    {"slug": "admin:subjects:update", "name": "Update subjects"},
    {"slug": "admin:subjects:delete", "name": "Delete subjects"},
    {"slug": "admin:academic-years:read", "name": "View academic years"},
    {"slug": "admin:academic-years:create", "name": "Create academic years"},
    {"slug": "admin:academic-years:update", "name": "Update academic years"},
    {"slug": "admin:academic-years:delete", "name": "Delete academic years"},
    {"slug": "admin:levels:read", "name": "View levels"},
    {"slug": "admin:levels:create", "name": "Create levels"},
    {"slug": "admin:levels:update", "name": "Update levels"},
    {"slug": "admin:levels:delete", "name": "Delete levels"},
    {"slug": "admin:fee-categories:read", "name": "View fee categories"},
    {"slug": "admin:fee-categories:create", "name": "Create fee categories"},
    {"slug": "admin:fee-categories:update", "name": "Update fee categories"},
    {"slug": "admin:fee-categories:delete", "name": "Delete fee categories"},
    {"slug": "admin:fee-variants:read", "name": "View fee variants"},
    {"slug": "admin:fee-variants:create", "name": "Create fee variants"},
    {"slug": "admin:fee-variants:update", "name": "Update fee variants"},
    {"slug": "admin:fee-variants:delete", "name": "Delete fee variants"},
    # Tranches (2) — le decoupage du total obligatoire dans le temps. Distinct
    # des categories de frais, qui sont des natures et non des echeances.
    {"slug": "admin:fee-installments:read", "name": "View the instalment grid"},
    {"slug": "admin:fee-installments:write", "name": "Set the instalment grid"},
    {"slug": "enrollments:schedule:write", "name": "Negotiate a family payment plan"},
    {"slug": "admin:fee-options:read", "name": "View fee options"},
    {"slug": "admin:fee-options:create", "name": "Create fee options"},
    {"slug": "admin:fee-options:update", "name": "Update fee options"},
    {"slug": "admin:fee-options:delete", "name": "Delete fee options"},
    # Academic (8)
    {"slug": "enrollments:read", "name": "View enrollments"},
    {"slug": "enrollments:create", "name": "Create enrollments"},
    {"slug": "enrollments:update", "name": "Update enrollments"},
    {"slug": "enrollments:delete", "name": "Delete enrollments"},
    {"slug": "enrollments:promote", "name": "Mass-promote enrollments year over year"},
    {"slug": "grades:read", "name": "View grades"},
    {"slug": "grades:write", "name": "Write grades"},
    {"slug": "grades:edit", "name": "Modify already-recorded grades"},
    {"slug": "bulletins:generate", "name": "Generate bulletins"},
    # Timetable (3)
    {"slug": "timetable:read", "name": "View timetable"},
    {"slug": "timetable:write", "name": "Edit timetable"},
    {"slug": "timetable:generate", "name": "Generate timetable"},
    # Operations (5)
    {"slug": "payments:read", "name": "View payments"},
    {"slug": "payments:create", "name": "Create payments"},
    # Caisse (4) — le caissier ne voit que ses propres versements. Le
    # cloisonnement se fait ici : `payments:read` seul ne donne accès qu'à sa
    # caisse, `payments:read:all` ouvre le journal de tout l'etablissement.
    {"slug": "payments:read:all", "name": "View every cashier's payments"},
    {"slug": "payments:cancel:any", "name": "Cancel any payment, including a closed day"},
    {"slug": "cash-session:manage", "name": "Open and close one's own cash day"},
    {"slug": "cash-session:read:all", "name": "View every cash day (daily reconciliation)"},
    {"slug": "attendance:read", "name": "View attendance"},
    {"slug": "attendance:create", "name": "Create attendance"},
    {"slug": "attendance:update", "name": "Update attendance"},
    # Reports (3)
    {"slug": "reports:read", "name": "View reports"},
    {"slug": "reports:generate", "name": "Generate reports"},
    {"slug": "reports:override", "name": "Override council decisions"},
    # Performance (1) — seedée par la migration 0034 mais absente de ce catalogue
    # jusqu'au 2026-08-20 : les tenants provisionnés depuis ce module n'avaient
    # donc pas le slug et /admin/performance repondait 403.
    {"slug": "performance:read", "name": "View teacher and staff performance"},
    # Teacher attendance (Phase 7b) (3)
    {"slug": "admin:teachers:attendance", "name": "Manage teacher attendance"},
    {"slug": "admin:teachers:attendance:read", "name": "View teacher attendance"},
    {"slug": "teacher:attendance:self_declare", "name": "Teacher self-declare absence"},
    # Official documents (3)
    {"slug": "documents:certificate", "name": "Generate certificat de scolarite"},
    {"slug": "documents:attendance", "name": "Generate attestation de frequentation"},
    {"slug": "documents:revoke", "name": "Revoke institutional document seals"},
    # Actes de vie scolaire — une permission par document, parce que ce ne sont
    # pas les memes bureaux qui les signent. La demande de dossier engage la
    # correspondance avec un autre etablissement et revient au directeur des
    # etudes ; les trois autres sont le quotidien de l'educateur.
    {"slug": "documents:school-file-request", "name": "Issue a school file request"},
    {"slug": "documents:entry-slip", "name": "Issue a class entry slip"},
    {"slug": "documents:parent-summons", "name": "Summon a parent and keep the register"},
    {"slug": "documents:zero-cancellation", "name": "Authorize a missed evaluation retake"},
    # Deroger a la retenue d'un document pour impaye. Direction seulement : la
    # personne qui constate la dette ne doit pas etre celle qui l'efface.
    {"slug": "documents:release:override", "name": "Release a document despite arrears"},
    # Journal d'audit. `audit:read` ouvre tout le journal ; `audit:read:financial`
    # n'ouvre que les ecritures d'argent — le comptable doit pouvoir remonter un
    # versement contesté sans lire les notes ni les dossiers medicaux au passage.
    # Etat de paiement sans montant : « a jour » ou « en retard », et la date du
    # dernier versement. De quoi valider un dossier d'inscription sans jamais
    # apprendre combien la famille doit.
    {"slug": "payments:status:read", "name": "See payment status without amounts"},
    # Corbeille. Archiver reste ouvert a qui pouvait deja supprimer ; vider la
    # corbeille est reserve a la direction, c'est le seul geste du logiciel
    # qui ne se rattrape pas.
    {"slug": "archive:read", "name": "Browse the recycle bin"},
    {"slug": "archive:purge", "name": "Permanently delete an archived record"},
    {"slug": "audit:read", "name": "Read the full audit journal"},
    {"slug": "audit:read:financial", "name": "Read the financial audit journal"},
    # Parents (4)
    {"slug": "admin:parents:read", "name": "View parents"},
    {"slug": "admin:parents:create", "name": "Create parents"},
    {"slug": "admin:parents:update", "name": "Update parents"},
    {"slug": "admin:parents:delete", "name": "Delete parents"},
    # Roles & Permissions management (2)
    {"slug": "admin:roles:read", "name": "View roles and permissions"},
    {"slug": "admin:roles:write", "name": "Manage roles and permissions"},
    # Rooms (4)
    {"slug": "admin:rooms:read", "name": "View rooms"},
    {"slug": "admin:rooms:create", "name": "Create rooms"},
    {"slug": "admin:rooms:update", "name": "Update rooms"},
    {"slug": "admin:rooms:delete", "name": "Delete rooms"},
    # Series (2)
    {"slug": "admin:series:read", "name": "View academic series"},
    {"slug": "admin:series:write", "name": "Manage academic series"},
    # Leave / congés (2)
    {"slug": "leave:request", "name": "Request leave"},
    {"slug": "leave:approve", "name": "Approve or reject leave requests"},
    # MailPulse (2)
    {"slug": "mailpulse:manage", "name": "Configure MailPulse notifications"},
    {"slug": "mailpulse:test", "name": "Send MailPulse test notifications"},
    # Comptes des acteurs (1)
    {"slug": "admin:accounts:manage", "name": "Manage actor login accounts"},
    # Super Admin (7)
    {"slug": "super-admin:tenants:create", "name": "Provision new tenants"},
    {"slug": "super-admin:tenants:read", "name": "View tenants list and per-tenant stats"},
    {"slug": "super-admin:tenants:status:write", "name": "Suspend / restore / archive a tenant"},
    {"slug": "super-admin:diagnose:read", "name": "Run platform and per-tenant diagnostics"},
    {"slug": "super-admin:logs:read", "name": "Read system logs (with redaction)"},
    {"slug": "super-admin:db:execute", "name": "Execute raw SQL queries against any tenant DB"},
    {"slug": "super-admin:pats:manage", "name": "Create / list / revoke personal access tokens"},
]


_SUPER_ADMIN_PERMS = [p["slug"] for p in ALL_PERMISSIONS if p["slug"].startswith("super-admin:")]


# ---------------------------------------------------------------------------
# Blocs reutilisables — evitent de recopier les memes listes dans chaque role
# et rendent les differences entre metiers lisibles d'un coup d'oeil.
# ---------------------------------------------------------------------------

# Referentiel que tout poste administratif doit pouvoir lire pour se reperer :
# sans l'annee courante, les ecrans qui filtrent par annee tombent en 403.
_REFERENTIEL_READ = [
    "admin:academic-years:read",
    "admin:levels:read",
    "admin:series:read",
    "admin:classes:read",
]

# Vue caisse d'un poste qui tient le guichet mais n'est pas cloisonne :
# le secretariat et la comptabilite voient toutes les caisses.
_CAISSE_SUPERVISION = [
    "payments:read:all",
    "cash-session:read:all",
]

# Configuration complete de la grille tarifaire (comptable uniquement).
_FEE_CONFIG = [
    "admin:fee-categories:read",
    "admin:fee-categories:create",
    "admin:fee-categories:update",
    "admin:fee-categories:delete",
    "admin:fee-variants:read",
    "admin:fee-variants:create",
    "admin:fee-variants:update",
    "admin:fee-variants:delete",
    "admin:fee-options:read",
    "admin:fee-options:create",
    "admin:fee-options:update",
    "admin:fee-options:delete",
    "admin:fee-installments:read",
    "admin:fee-installments:write",
    "enrollments:schedule:write",
]

# Lecture seule des tranches : savoir ce que la famille doit et quand, sans
# pouvoir toucher a la grille.
_INSTALLMENTS_READ = ["admin:fee-installments:read"]

# Les trois actes du bureau de la vie scolaire : billet d'entree, convocation
# du tuteur, annulation de zero. Ils vont ensemble parce qu'ils traitent tous
# de la meme journee d'eleve, et que la personne qui en signe un signe les
# autres.
_SCHOOL_LIFE_ACTS = [
    "documents:entry-slip",
    "documents:parent-summons",
    "documents:zero-cancellation",
]


ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "admin": {
        "description": "Administrateur — accès complet du tenant",
        "permissions": [
            p["slug"] for p in ALL_PERMISSIONS if not p["slug"].startswith("super-admin:")
        ],
    },
    "director": {
        "description": "Directeur d'établissement",
        "permissions": [
            p["slug"] for p in ALL_PERMISSIONS if not p["slug"].startswith("super-admin:")
        ],
    },
    "teacher": {
        "description": "Enseignant",
        "permissions": [
            "grades:read",
            "grades:write",
            "grades:edit",
            "bulletins:generate",
            "attendance:read",
            "attendance:create",
            "attendance:update",
            "timetable:read",
            "reports:read",
            "teacher:attendance:self_declare",
            "leave:request",
        ],
    },
    # Slug historique `staff`, conserve tel quel : il est porte par des comptes
    # en production, inscrit dans le JWT et reference dans l'audit. Seul le
    # libelle passe a « Secretariat ».
    "staff": {
        "description": "Secrétariat",
        "permissions": [
            "enrollments:read",
            "enrollments:create",
            "enrollments:update",
            "payments:read",
            "payments:create",
            "cash-session:manage",
            "admin:students:read",
            "admin:students:create",
            "admin:students:update",
            "admin:parents:read",
            "admin:parents:create",
            "admin:parents:update",
            *_REFERENTIEL_READ,
            "attendance:read",
            "reports:read",
            "admin:teachers:attendance",
            "admin:teachers:attendance:read",
            "admin:accounts:manage",
            *_INSTALLMENTS_READ,
            "documents:certificate",
            "documents:attendance",
            # Le secretariat est le guichet : il edite les quatre actes, y
            # compris la demande de dossier qu'il poste ensuite.
            "documents:school-file-request",
            *_SCHOOL_LIFE_ACTS,
            "leave:request",
        ],
    },
    # Le comptable configure la grille tarifaire et consolide toutes les caisses.
    # Il lui manquait `admin:academic-years:read`, ce qui faisait echouer en 403
    # tous les ecrans filtrant par annee — dont la page Frais elle-meme.
    "accountant": {
        "description": "Comptable / Trésorier",
        "permissions": [
            "payments:read",
            "payments:create",
            *_CAISSE_SUPERVISION,
            "audit:read:financial",
            "payments:cancel:any",
            "enrollments:read",
            "admin:students:read",
            *_REFERENTIEL_READ,
            *_FEE_CONFIG,
            "reports:read",
            "reports:generate",
            "leave:request",
            "admin:levels:create",
            "admin:levels:update",
            "admin:levels:delete",
            "admin:series:write",
        ],
    },
    # Le caissier encaisse au guichet. Il ne voit que ses propres versements :
    # le cloisonnement est applique cote service, `payments:read` ne suffit pas
    # a lui ouvrir les caisses des collegues.
    "cashier": {
        "description": "Caissier / Caissière",
        "permissions": [
            # Volontairement SANS `payments:read:all` ni `cash-session:read:all` :
            # c'est ce qui le cantonne a sa propre caisse.
            "payments:read",
            "payments:create",
            "cash-session:manage",
            *_INSTALLMENTS_READ,
            "enrollments:read",
            "admin:students:read",
            *_REFERENTIEL_READ,
            "leave:request",
        ],
    },
    # L'educateur monte les inscriptions et reinscriptions, puis valide une fois
    # l'encaissement passe en caisse. Il lit les paiements sans pouvoir en creer.
    "educator": {
        "description": "Éducateur",
        "permissions": [
            "enrollments:read",
            "enrollments:create",
            "enrollments:update",
            "admin:students:read",
            "admin:students:create",
            "admin:students:update",
            "admin:parents:read",
            "admin:parents:create",
            "admin:parents:update",
            *_REFERENTIEL_READ,
            "payments:status:read",
            *_INSTALLMENTS_READ,
            "attendance:read",
            "reports:read",
            "documents:certificate",
            "documents:attendance",
            # Billet d'entree, convocation, annulation de zero : le coeur du
            # bureau de la vie scolaire. Pas la demande de dossier, qui sort de
            # l'etablissement et reste au directeur des etudes.
            *_SCHOOL_LIFE_ACTS,
            "leave:request",
        ],
    },
    # Le directeur des etudes pilote tout le pedagogique et rien du financier :
    # aucune permission `payments:*` ni `admin:fee-*`.
    "studies_director": {
        "description": "Directeur des études",
        "permissions": [
            *_REFERENTIEL_READ,
            "admin:classes:create",
            "admin:classes:update",
            "admin:series:write",
            "admin:rooms:read",
            "admin:rooms:create",
            "admin:rooms:update",
            "admin:subjects:read",
            "admin:subjects:create",
            "admin:subjects:update",
            "admin:subjects:delete",
            "admin:teachers:read",
            "admin:teachers:update",
            "admin:teachers:attendance",
            "admin:teachers:attendance:read",
            "admin:students:read",
            "enrollments:read",
            "timetable:read",
            "timetable:write",
            "timetable:generate",
            "grades:read",
            "grades:write",
            "grades:edit",
            "bulletins:generate",
            "attendance:read",
            "attendance:create",
            "attendance:update",
            "reports:read",
            "reports:generate",
            "reports:override",
            "performance:read",
            "documents:certificate",
            "documents:attendance",
            # Il signe la demande de dossier scolaire : c'est lui qui
            # correspond avec l'etablissement d'origine.
            "documents:school-file-request",
            "leave:request",
            "leave:approve",
            "payments:status:read",
        ],
    },
    "student": {
        "description": "Élève — accès portail élève uniquement",
        "permissions": [],
    },
    "parent": {
        "description": "Parent / Tuteur — accès portail parent uniquement",
        "permissions": [],
    },
    "super_admin": {
        "description": "Super Administrateur — operations multi-tenant et plateforme",
        "permissions": _SUPER_ADMIN_PERMS,
    },
}
# Note: student and parent roles have NO permissions (portal is user-scoped via JWT)
