"""Critères communs des listes de classe, sans modifier l'effectif officiel."""
from datetime import date
from pydantic import BaseModel, Field, model_validator

class RosterFilters(BaseModel):
    genre: str | None = None
    age_min: int | None = Field(None, ge=0, le=120)
    age_max: int | None = Field(None, ge=0, le=120)
    nationalities: list[str] = Field(default_factory=list)
    assignments: list[str] = Field(default_factory=list)
    repeaters: bool | None = None

    @model_validator(mode="after")
    def check(self):
        if self.genre not in (None, "M", "F"):
            raise ValueError("Genre invalide")
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("Age minimum superieur au maximum")
        if any(x not in ("affecte", "reaffecte", "non_affecte", "inconnu") for x in self.assignments):
            raise ValueError("Statut d'affectation invalide")
        return self

def filter_roster(students: list[dict], filters: RosterFilters, today: date | None = None) -> list[dict]:
    today = today or date.today()
    names = {s.casefold().strip() for s in filters.nationalities if s.strip()}
    statuses = set(filters.assignments)
    rows = []
    for s in students:
        if filters.genre and s.get("genre") != filters.genre:
            continue
        born = s.get("birth_date")
        if filters.age_min is not None or filters.age_max is not None:
            if not born:
                continue
            age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
            if (filters.age_min is not None and age < filters.age_min) or (filters.age_max is not None and age > filters.age_max):
                continue
        if names and (s.get("nationality") or "").casefold().strip() not in names:
            continue
        if statuses and (s.get("assignment_status") or "inconnu") not in statuses:
            continue
        if filters.repeaters is not None and s.get("is_repeater") is not filters.repeaters:
            continue
        rows.append(s)
    return rows
