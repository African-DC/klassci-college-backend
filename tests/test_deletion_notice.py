"""Le courriel de suppression — destinataires, contenu, et le fait qu'il ne bloque rien.

Ce que ces tests protègent, c'est une promesse faite au chef d'établissement :
il apprendra toute suppression par sa boîte de réception, hors du logiciel.
Et une promesse inverse faite à la secrétaire : aucun serveur de messagerie
en panne ne l'empêchera de corriger une fiche créée en double.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services import deletion_notice_service as notice
from app.services.archive_service import ArchiveOutcome


def _school(**kwargs: object) -> SimpleNamespace:
    base = {
        "school_name": "Collège Saint-Augustin",
        "email": None,
        "deletion_notice_emails": None,
        "head_master_name": "Mme Diallo",
        "mailpulse_enabled": False,
        "mailpulse_sender_email": None,
        "mailpulse_sender_name": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _outcome(**kwargs: object) -> ArchiveOutcome:
    base: dict = {
        "entity_type": "student",
        "entity_id": 42,
        "label": "L'élève Traoré Aminata",
        "reason": "Fiche créée en double lors de la rentrée",
        "permanent": False,
    }
    base.update(kwargs)
    return ArchiveOutcome(**base)


# ---------------------------------------------------------------------------
# À qui part le courriel
# ---------------------------------------------------------------------------


def test_la_liste_configuree_est_utilisee_telle_quelle() -> None:
    school = _school(deletion_notice_emails="direction@ecole.ci, compta@ecole.ci")
    assert notice.resolve_recipients(school) == ["direction@ecole.ci", "compta@ecole.ci"]


def test_les_separateurs_courants_sont_tolerés() -> None:
    """Une école qui colle trois adresses depuis un tableur ne doit pas voir
    son courriel partir dans le vide à cause d'un point-virgule."""
    school = _school(deletion_notice_emails="a@x.ci; b@x.ci\nc@x.ci")
    assert notice.resolve_recipients(school) == ["a@x.ci", "b@x.ci", "c@x.ci"]


def test_les_doublons_et_les_non_adresses_sont_ecartes() -> None:
    school = _school(deletion_notice_emails="a@x.ci, a@x.ci, Mme Diallo, ,b@x.ci")
    assert notice.resolve_recipients(school) == ["a@x.ci", "b@x.ci"]


def test_sans_liste_on_retombe_sur_l_adresse_de_l_ecole() -> None:
    """Le repli : dans la quasi-totalité des collèges, l'adresse de
    l'établissement est celle du chef d'établissement."""
    school = _school(email="direction@saint-augustin.ci")
    assert notice.resolve_recipients(school) == ["direction@saint-augustin.ci"]


def test_sans_rien_de_configure_il_n_y_a_aucun_destinataire() -> None:
    assert notice.resolve_recipients(_school()) == []


@pytest.mark.asyncio
async def test_sans_destinataire_on_avertit_mais_on_ne_bloque_pas(monkeypatch, caplog) -> None:
    """Une suppression ne doit jamais échouer parce qu'un courriel n'a nulle
    part où aller. On le dit fort dans les journaux, et on continue."""
    school = _school()

    async def _fake_settings(_db: object) -> SimpleNamespace:
        return school

    monkeypatch.setattr(
        "app.services.admin_service.get_school_settings", _fake_settings, raising=False
    )

    with caplog.at_level("WARNING"):
        envoye = await notice.send_deletion_notice(object(), _outcome())

    assert envoye is False
    assert any("destinataire" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# Ce que dit le courriel
# ---------------------------------------------------------------------------


def _compose(**kwargs: object) -> tuple[str, str, str]:
    return notice.compose_notice(
        _outcome(**kwargs),
        school=_school(),
        actor_name="Sophie Yao (sophie@ecole.ci)",
        occurred_at=datetime(2026, 8, 20, 14, 30),
    )


def test_le_courriel_dit_qui_quand_quoi_et_pourquoi() -> None:
    """Les quatre questions qu'on se pose trois mois plus tard, devant une
    fiche qui n'est plus là."""
    _subject, texte, _html = _compose()
    assert "Sophie Yao" in texte
    assert "20/08/2026 à 14:30" in texte
    assert "Traoré Aminata" in texte
    assert "Fiche créée en double lors de la rentrée" in texte


def test_le_motif_figure_aussi_dans_la_version_html() -> None:
    _subject, _texte, html = _compose()
    assert "Fiche créée en double lors de la rentrée" in html


def test_l_objet_distingue_l_archivage_de_la_suppression() -> None:
    """Un chef d'établissement doit savoir, au seul objet, s'il doit réagir."""
    objet_corbeille, _, _ = _compose(permanent=False)
    objet_definitif, _, _ = _compose(permanent=True)
    assert "Mise à la corbeille" in objet_corbeille
    assert "Suppression définitive" in objet_definitif


def test_l_archivage_annonce_qu_on_peut_revenir_en_arriere() -> None:
    _subject, texte, _html = _compose(permanent=False)
    assert "restaurée" in texte
    assert "rien n'a été détruit" in texte


def test_la_suppression_definitive_annonce_l_irreversible() -> None:
    _subject, texte, _html = _compose(permanent=True)
    assert "ne peut plus être restaurée" in texte


def test_le_courriel_enumere_ce_qui_est_parti_avec_la_fiche() -> None:
    """« Supprimé » sans dire quoi ne vaut guère mieux que pas de trace."""
    _subject, texte, html = _compose(
        permanent=True,
        carried_away=("1 inscription", "6 frais d'élève", "3 versements conservés"),
    )
    for phrase in ("1 inscription", "6 frais d'élève", "3 versements conservés"):
        assert phrase in texte
        assert phrase in html


def test_le_courriel_rassure_explicitement_sur_les_versements() -> None:
    """C'est la question que pose une comptable en lisant « supprimé »."""
    _subject, texte, _html = _compose(permanent=True, carried_away=("2 versements conservés",))
    assert "versements encaissés, eux, sont conservés" in texte


def test_le_courriel_ne_parle_pas_le_jargon_de_la_base() -> None:
    """Il est lu par un chef d'établissement, pas par un développeur."""
    _subject, texte, _html = _compose()
    for jargon in ("student", "entity_type", "enrollment", "None", "null"):
        assert jargon not in texte


# ---------------------------------------------------------------------------
# L'envoi n'empêche jamais la suppression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_smtp_en_panne_ne_bloque_pas_la_suppression(monkeypatch) -> None:
    school = _school(deletion_notice_emails="direction@ecole.ci")

    async def _fake_settings(_db: object) -> SimpleNamespace:
        return school

    def _smtp_casse(*_args: object, **_kwargs: object) -> bool:
        raise OSError("connexion refusée")

    monkeypatch.setattr(
        "app.services.admin_service.get_school_settings", _fake_settings, raising=False
    )
    monkeypatch.setattr("app.services.email_service.send_email", _smtp_casse)

    # `send_deletion_notice` remonte l'erreur, mais `archive_service.notify`
    # est le point de branchement réel : c'est lui qui doit l'absorber.
    from app.services import archive_service

    await archive_service.notify(object(), _outcome())  # ne doit pas lever


@pytest.mark.asyncio
async def test_un_refus_d_envoi_est_signale_sans_lever(monkeypatch, caplog) -> None:
    """`send_email` renvoie False quand SMTP n'est pas configuré : on le
    journalise plutôt que de laisser croire que la trace est partie."""
    school = _school(deletion_notice_emails="direction@ecole.ci")

    async def _fake_settings(_db: object) -> SimpleNamespace:
        return school

    async def _fake_actor(_db: object, _actor_id: int) -> str:
        return "Sophie Yao"

    monkeypatch.setattr(
        "app.services.admin_service.get_school_settings", _fake_settings, raising=False
    )
    monkeypatch.setattr(notice, "_resolve_actor_name", _fake_actor)
    monkeypatch.setattr("app.services.email_service.send_email", lambda *a, **k: False)

    with caplog.at_level("WARNING"):
        envoye = await notice.send_deletion_notice(object(), _outcome())

    assert envoye is False
    assert any("courriel de suppression" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_le_courriel_part_bien_quand_smtp_repond(monkeypatch) -> None:
    school = _school(deletion_notice_emails="direction@ecole.ci, compta@ecole.ci")
    envois: list[tuple[str, str]] = []

    async def _fake_settings(_db: object) -> SimpleNamespace:
        return school

    async def _fake_actor(_db: object, _actor_id: int) -> str:
        return "Sophie Yao"

    monkeypatch.setattr(
        "app.services.admin_service.get_school_settings", _fake_settings, raising=False
    )
    monkeypatch.setattr(notice, "_resolve_actor_name", _fake_actor)
    monkeypatch.setattr(
        "app.services.email_service.send_email",
        lambda to, subject, html, text=None: envois.append((to, subject)) or True,
    )

    assert await notice.send_deletion_notice(object(), _outcome()) is True
    assert [to for to, _ in envois] == ["direction@ecole.ci", "compta@ecole.ci"]
