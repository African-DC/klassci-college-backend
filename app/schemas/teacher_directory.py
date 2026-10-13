"""Options et validation commune à tous les exports d'enseignants du Collège."""

from pydantic import BaseModel, Field, model_validator


COLUMNS: dict[str, str] = {
    "name": "Nom et prénoms",
    "speciality": "Spécialité déclarée",
    "subject": "Matière",
    "class": "Classe",
    "level": "Niveau",
    "series": "Série",
    "contract": "Contrat",
    "gender": "Sexe",
    "phone": "Téléphone",
    "email": "Email",
    "source": "Origine de l'affectation",
    "cnps": "N° CNPS",
    "authorization": "N° autorisation",
}
GROUPS: dict[str, str] = {
    "subject": "Par matière",
    "speciality": "Par spécialité",
    "class": "Par classe",
    "level": "Par niveau",
    "series": "Par série",
    "contract": "Par contrat",
    "none": "Sans regroupement",
}
DEFAULT_COLUMNS = ["name", "subject", "class", "level"]
# Largeurs minimales indicatives en mm : le PDF utilise la même heuristique.
COLUMN_WIDTHS = {
    "name": 58, "speciality": 42, "subject": 44, "class": 31,
    "level": 27, "series": 20, "contract": 25, "gender": 14,
    "phone": 35, "email": 48, "source": 40,
    "cnps": 35, "authorization": 42,
}


class TeacherExportOptions(BaseModel):
    """Un seul payload pour l'aperçu, PDF, Word et Excel."""

    academic_year_id: int | None = Field(default=None, gt=0)
    search: str = Field(default="", max_length=150)
    class_ids: list[int] = Field(default_factory=list, max_length=100)
    level_ids: list[int] = Field(default_factory=list, max_length=100)
    series_ids: list[int] = Field(default_factory=list, max_length=100)
    subject_ids: list[int] = Field(default_factory=list, max_length=100)
    teacher_ids: list[int] = Field(default_factory=list, max_length=100)
    contract_types: list[str] = Field(
        default_factory=list
    )
    columns: list[str] = Field(default_factory=lambda: list(DEFAULT_COLUMNS), min_length=1, max_length=13)
    group_by: str = "subject"
    orientation: str = "auto"
    # Les enseignants sans affectation peuvent figurer uniquement si la demande
    # ne requiert pas de portée pédagogique particulière.
    include_unassigned: bool = True
    # Sources : EDT de l'année choisie, ou matière attribuée sans classe/année.
    include_catalog: bool = True

    @model_validator(mode="after")
    def valid_selection(self) -> "TeacherExportOptions":
        if self.group_by not in GROUPS or self.orientation not in {"auto", "portrait", "landscape"}:
            raise ValueError("Regroupement ou orientation inconnue.")
        if any(value not in {"permanent", "vacataire", "fonctionnaire"} for value in self.contract_types):
            raise ValueError("Type de contrat inconnu.")
        if len(set(self.columns)) != len(self.columns) or any(c not in COLUMNS for c in self.columns):
            raise ValueError("Choisissez uniquement des colonnes connues, sans doublon.")
        for name in ("class_ids", "level_ids", "series_ids", "subject_ids", "teacher_ids"):
            values = getattr(self, name)
            if len(set(values)) != len(values) or any(v <= 0 for v in values):
                raise ValueError(f"Filtre {name} invalide : doublons ou identifiants négatifs.")
        # Les filtres ne sont pas des colonnes : « nom seul » est valide même
        # avec plusieurs matières et sans rubrique explicite.
        return self


def page_orientation(opts: TeacherExportOptions) -> str:
    width = sum(COLUMN_WIDTHS[key] for key in opts.columns)
    if width > 265:
        raise ValueError("Trop de colonnes pour une page A4 paysage. Réduisez votre sélection.")
    if opts.orientation == "portrait":
        if width > 180:
            raise ValueError("Les colonnes sont trop larges pour A4 portrait.")
        return "portrait"
    if opts.orientation == "landscape":
        return "landscape"
    return "portrait" if width <= 180 else "landscape"
