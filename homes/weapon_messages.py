PERSON_WEAPON_TITLE = "Personne détectée avec port d’arme probable"


def person_weapon_suspected(metadata):
    evidence = (metadata or {}).get("weapon_verification") or {}
    return evidence.get("state") == "suspected" and evidence.get("person_associated") is True
