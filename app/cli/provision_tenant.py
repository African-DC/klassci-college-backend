"""CLI — Provisionner un nouveau tenant.

Usage:
    python -m app.cli.provision_tenant \\
        --slug lycee-moderne \\
        --school "Lycée Moderne d'Abidjan" \\
        --admin-email admin@lycee-moderne.ci \\
        --admin-password "SecureP@ss123" \\
        --admin-first-name "Aboubacar"

Le welcome email est envoyé automatiquement si SMTP est configuré (best-effort).
Désactiver avec --no-welcome-email si besoin (ex: re-provisioning d'un tenant existant).
"""

import argparse
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Provisionner un nouveau tenant KLASSCI")
    parser.add_argument("--slug", required=True, help="Identifiant unique du tenant (sous-domaine)")
    parser.add_argument("--school", required=True, help="Nom de l'établissement")
    parser.add_argument("--admin-email", required=True, help="Email du compte admin")
    parser.add_argument("--admin-password", required=True, help="Mot de passe admin initial")
    parser.add_argument(
        "--admin-first-name",
        default="",
        help="Prénom de l'admin (utilisé dans le welcome email)",
    )
    parser.add_argument("--address", default=None, help="Adresse de l'établissement")
    parser.add_argument("--phone", default=None, help="Téléphone")
    parser.add_argument("--school-email", default=None, help="Email de l'établissement")
    parser.add_argument("--ministry-code", default=None, help="Code ministère / DREN")
    parser.add_argument(
        "--no-welcome-email",
        action="store_true",
        help="Ne pas envoyer le welcome email (utile pour re-provisioning)",
    )
    args = parser.parse_args()

    from app.services.tenant_service import provision_tenant

    try:
        result = asyncio.run(
            provision_tenant(
                tenant_slug=args.slug,
                school_name=args.school,
                admin_email=args.admin_email,
                admin_password=args.admin_password,
                admin_first_name=args.admin_first_name,
                school_address=args.address,
                school_phone=args.phone,
                school_email=args.school_email,
                ministry_code=args.ministry_code,
                send_welcome_email=not args.no_welcome_email,
            )
        )
        print(f"\nTenant '{result['tenant_slug']}' provisionned successfully!")
        print(f"   Database     : {result['database']}")
        print(f"   Admin email  : {result['admin_email']}")
        print(f"   URL          : {result['tenant_url']}")
        if not args.no_welcome_email:
            if result["welcome_email_sent"]:
                print(f"   Welcome mail : SENT to {result['admin_email']}")
            else:
                print("   Welcome mail : SKIPPED (SMTP non configuré ou erreur)")
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
