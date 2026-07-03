"""KLASSCI Collège — Backend API.

Point d'entrée de l'application FastAPI.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.middleware import TenantMiddleware
from app.core.sentry import init_sentry
from app.routers.admin import router as admin_router
from app.routers.attachments import router as attachments_router
from app.routers.attendance import router as attendance_router
from app.routers.auth import router as auth_router
from app.routers.class_documents import router as class_documents_router
from app.routers.council import router as council_router
from app.routers.dashboard import router as dashboard_router
from app.routers.dren_stats import router as dren_stats_router
from app.routers.enrollment_payments import router as enrollment_payments_router
from app.routers.enrollments import router as enrollments_router
from app.routers.fees import router as fees_router
from app.routers.grades import router as grades_router
from app.routers.leave import admin_router as leave_admin_router
from app.routers.leave import self_router as leave_self_router
from app.routers.notifications import router as notifications_router
from app.routers.parent_portal import router as parent_portal_router
from app.routers.payments import router as payments_router
from app.routers.performance import admin_router as performance_admin_router
from app.routers.performance import teacher_router as performance_teacher_router
from app.routers.profile import router as profile_router
from app.routers.promotions import router as promotions_router
from app.routers.public_verify import router as public_verify_router
from app.routers.reports import router as reports_router
from app.routers.student_documents import router as student_documents_router
from app.routers.student_portal import router as student_portal_router
from app.routers.super_admin import router as super_admin_router
from app.routers.teacher_attendance import admin_router as teacher_attendance_admin_router
from app.routers.teacher_attendance import teacher_router as teacher_attendance_teacher_router
from app.routers.teacher_portal import router as teacher_portal_router
from app.routers.timetable import availability_router, teachers_router
from app.routers.timetable import router as timetable_router

# Sentry must be initialized BEFORE FastAPI() so its middleware attaches.
# No-op if SENTRY_DSN is empty.
init_sentry()

app = FastAPI(
    title=settings.APP_NAME,
    description="API de gestion scolaire multi-tenant",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# --- Static files (uploads) ---
UPLOAD_DIR = "/tmp/klassci-uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# --- Middleware (ordre : dernier ajouté = premier exécuté) ---
# TenantMiddleware ajouté en 1er → s'exécute en dernier (inner layer)
# CORSMiddleware ajouté en 2ème → s'exécute en premier (outer layer)
# Ainsi les preflight CORS sont traités avant la résolution tenant.
app.add_middleware(TenantMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Handlers d'exception ---
register_exception_handlers(app)

# --- Routers ---
app.include_router(admin_router)
app.include_router(attachments_router)
app.include_router(attendance_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(enrollments_router)
app.include_router(enrollment_payments_router)
app.include_router(class_documents_router)
app.include_router(fees_router)
app.include_router(grades_router)
app.include_router(leave_self_router)
app.include_router(leave_admin_router)
app.include_router(notifications_router)
app.include_router(payments_router)
app.include_router(promotions_router)
app.include_router(public_verify_router)
app.include_router(student_portal_router)
app.include_router(parent_portal_router)
app.include_router(teacher_portal_router)
app.include_router(reports_router)
app.include_router(student_documents_router)
app.include_router(council_router)
app.include_router(dren_stats_router)
app.include_router(super_admin_router)
app.include_router(timetable_router)
app.include_router(teachers_router)
app.include_router(availability_router)
app.include_router(teacher_attendance_admin_router)
app.include_router(teacher_attendance_teacher_router)
app.include_router(performance_admin_router)
app.include_router(performance_teacher_router)
app.include_router(profile_router)


# ---------------------------------------------------------------------------
# Routes de base
# ---------------------------------------------------------------------------


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Vérification de santé — utilisé par le CI et le load balancer."""
    return {"status": "ok"}
