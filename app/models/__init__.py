"""app/models — importe tous les modèles pour enregistrer leurs tables dans Base.metadata.

L'ordre d'import respecte les dépendances FK :
  base → academic → user → enrollment → fee → timetable → grade → attendance → permission → notification → message → audit
"""

# Dépendances de base (pas de FK vers d'autres modèles de ce package)
from app.models.academic import (  # noqa: F401
    AcademicYear,
    Class,
    Level,
    Room,
    SchoolSettings,
    Series,
    Subject,
)

# Présences
from app.models.attendance import (  # noqa: F401
    AttendanceContext,
    AttendanceEntityType,
    AttendanceRecord,
    AttendanceSource,
    AttendanceStatus,
)

# Audit log (défini dans app.core.audit, re-exporté ici)
from app.models.audit import AuditAction, AuditLog  # noqa: F401

# Inscriptions
from app.models.enrollment import (  # noqa: F401
    Document,
    Enrollment,
    EnrollmentStatus,
    StudentOption,
)

# Frais et paiements
from app.models.fee import (  # noqa: F401
    EnrollmentFee,
    EnrollmentFeeStatus,
    FeeCategory,
    FeeVariant,
    OptionalFeeOption,
    Payment,
    PaymentMethod,
    PaymentStatus,
)

# Notes et bulletins
from app.models.grade import (  # noqa: F401
    Bulletin,
    CouncilDecision,
    CouncilMinutes,
    CouncilStudentDecision,
    Evaluation,
    EvaluationType,
    Grade,
    GradeStatus,
    Mention,
)

# Messagerie interne
from app.models.message import Message  # noqa: F401

# Notifications
from app.models.notification import (  # noqa: F401
    Notification,
    NotificationChannel,
    NotificationTemplate,
    NotificationType,
)

# Rôles et permissions
from app.models.permission import (  # noqa: F401
    Permission,
    Role,
    RolePermission,
    UserRole,
)

# Emploi du temps
from app.models.timetable import (  # noqa: F401
    DayOfWeek,
    TeacherAvailability,
    Timetable,
    TimetableSlot,
)

# Utilisateurs et profils
from app.models.user import (  # noqa: F401
    Genre,
    Parent,
    ParentRelationship,
    ParentStudent,
    StaffProfile,
    Student,
    TeacherProfile,
    User,
    UserRoleEnum,
)
