"""Les deux tableaux DRENA que le type de contrat et le sexe débloquent."""

from app.models.user import TeacherContract


def test_les_trois_types_de_contrat_de_la_drena_existent() -> None:
    """Le canevas distingue permanents, vacataires et fonctionnaires."""
    assert {c.value for c in TeacherContract} == {"permanent", "vacataire", "fonctionnaire"}


def test_les_deux_tableaux_ne_sont_plus_en_attente() -> None:
    """Ils étaient imprimés vierges faute de données ; ils se calculent
    désormais, et un rapport déposé à la DRENA n'a plus deux trous."""
    import inspect

    from app.services.deep_report import chapter3_teachers as chapter

    for nom in ("_contract_table", "_discipline_by_gender_table"):
        source = inspect.getsource(getattr(chapter, nom))
        assert "pending=True" not in source, f"{nom} est encore marqué à compléter"
        assert "context" in inspect.signature(getattr(chapter, nom)).parameters


def test_un_enseignant_sans_sexe_ne_disparait_pas_des_totaux() -> None:
    """Le ranger arbitrairement en F ou G ferait dire au rapport une chose que
    personne n'a constatée ; l'oublier ferait mentir le total."""
    import inspect

    from app.services.deep_report import chapter3_teachers as chapter

    source = inspect.getsource(chapter._contract_table)
    assert 'counts["T"] += 1' in source, "le total doit compter tout le monde"
    assert 'if genre in ("F", "G")' in source, "la ventilation doit exclure les non renseignés"
    assert "sans sexe renseigné" in source, "la note doit le dire au lecteur"
