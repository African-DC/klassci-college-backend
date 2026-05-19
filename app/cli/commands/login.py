"""`klassci login` — store a PAT in the OS keyring after verifying it."""

import getpass
import sys

import click
import httpx

from app.cli.auth import delete_token, save_token


@click.command("login")
@click.option("--profile", default="default", help="Auth profile name in keyring.")
@click.option(
    "--api-url",
    envvar="KLASSCI_API_URL",
    default="https://college.klassci.com",
    show_default=True,
)
@click.option("--token", default=None, help="Paste the PAT directly (skip interactive prompt).")
@click.option("--logout", is_flag=True, help="Remove the stored token for the profile.")
def login(profile: str, api_url: str, token: str | None, logout: bool) -> None:
    """Authenticate the CLI with a PAT minted via /super-admin/pats."""
    if logout:
        delete_token(profile)
        click.secho(f"Profil '{profile}' supprimé du keyring.", fg="yellow")
        return

    if not token:
        click.echo(f"Colle un token klc_pat_* pour le profil '{profile}' :")
        token = getpass.getpass("Token : ").strip()

    if not token.startswith("klc_pat_"):
        raise click.ClickException("Format invalide (attendu : klc_pat_*).")

    try:
        resp = httpx.get(
            f"{api_url.rstrip('/')}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise click.ClickException(f"Impossible de joindre {api_url} : {exc}") from exc

    if resp.status_code != 200:
        raise click.ClickException(
            f"Token rejeté par le serveur ({resp.status_code}). Vérifie la valeur et le scope."
        )

    me = resp.json()
    save_token(profile, token)
    click.secho(
        f"Connecté en tant que {me.get('email', '?')} (profil '{profile}').",
        fg="green",
    )
    sys.exit(0)
