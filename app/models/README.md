# app/models/ — Modèles SQLAlchemy

Un fichier par domaine métier. Tous héritent de `Base` et `TimestampMixin`.

## Convention

```python
class MonModel(Base, TimestampMixin):
    __tablename__ = "nom_pluriel"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
```

## Fichiers à créer

| Fichier | Modèles |
|---------|---------|
| `base.py` | `Base`, `TimestampMixin` |
| `user.py` | `User`, `StaffProfile`, `TeacherProfile`, `Student`, `Parent`, `ParentStudent` |
| `academic.py` | `AcademicYear`, `Level`, `Series`, `Class`, `Subject`, `Room`, `SchoolSettings` |
| `enrollment.py` | `Enrollment`, `Document`, `StudentOption` |
| `fee.py` | `FeeCategory`, `FeeVariant`, `OptionalFeeOption`, `EnrollmentFee`, `Payment` |
| `timetable.py` | `Timetable`, `TimetableSlot`, `TeacherAvailability` |
| `grade.py` | `EvaluationType`, `Evaluation`, `Grade`, `Bulletin` |
| `attendance.py` | `AttendanceContext`, `AttendanceRecord` |
| `permission.py` | `Role`, `Permission`, `RolePermission`, `UserRole` |
| `notification.py` | `Notification`, `NotificationTemplate` |
| `audit.py` | `AuditLog` |
| `message.py` | `Message` |
