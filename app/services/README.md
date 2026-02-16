# app/services/ — Logique Metier

Toute la logique business de KLASSCI vit ici. Rien d'autre.

## Convention

```python
class EnrollmentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = EnrollmentRepository(db)

    async def create(self, data: EnrollmentCreate, created_by: int) -> Enrollment:
        # 1. Valider les regles metier
        await self._validate_fee_structure(data.class_id)
        # 2. Effectuer l operation
        enrollment = await self.repo.create(data, created_by)
        # 3. Audit log obligatoire
        await audit_log(self.db, "enrollment", enrollment.id, "create", None, enrollment)
        return enrollment
```

## Services a creer

| Service | Responsabilites |
|---------|----------------|
| `EnrollmentService` | Workflow inscription, transitions de statut |
| `FeeService` | Calcul frais, application variants, paiements |
| `TimetableService` | Generation EDT (OR-Tools), validation conflits |
| `GradeService` | Saisie notes, detection manquants, calcul moyennes |
| `BulletinService` | Generation bulletins PDF via Puppeteer |
| `AttendanceService` | Appel, pointage cantine/transport |
| `NotificationService` | Envoi in-app/email/SMS/WhatsApp |
| `PermissionService` | Verification RBAC dynamique |
| `TenantService` | Provisioning tenant, migrations multi-DB |
