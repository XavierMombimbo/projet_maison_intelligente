"""Human-readable summaries; never infer delivery or identity from a score."""
from django import template
from homes.weapon_messages import PERSON_WEAPON_TITLE, person_weapon_suspected

register = template.Library()


@register.filter
def event_summary(event):
    metadata = event.metadonnees or {}
    if metadata.get("academic_weapon_demo"):
        return dict(title="Démo académique — suspicion d’arme", heading="Alerte d’essai",
                    icon="eye", weapon=True, demo=True, style="neutral", quiet=False,
                    message="Résultat expérimental à vérifier. Cet essai ne prouve pas une menace.",
                    badge="Essai académique", notification="Sur l’écran du test uniquement",
                    siren="Non demandée")
    if (metadata.get("weapon_verification") or {}).get("state") == "suspected":
        weapon_status = {"new": "À vérifier · Urgent", "confirmed": "Signalement confirmé", "false_alarm": "Fausse alerte"}
        return dict(title=PERSON_WEAPON_TITLE if person_weapon_suspected(metadata) else "Suspicion d’arme", heading=weapon_status.get(event.statut, "Objet à vérifier"), icon="eye", weapon=True,
                    message="Un objet ressemble à une arme. Vérifiez l’image avant toute décision.",
                    badge=weapon_status.get(event.statut, "À vérifier"),
                    style=event.statut, quiet=False,
                    notification="Pas de nouvel envoi" if event.notification_supprimee else "Selon vos préférences",
                    siren="Pas de nouveau signal" if event.notification_supprimee else "Selon vos réglages")
    quiet_presence = bool(event.notification_supprimee and
                          metadata.get("alerte", {}).get("notification_supprimee"))
    if quiet_presence:
        return dict(title="Présence détectée", heading="Personne reconnue", icon="person-check",
                    message="La présence a été enregistrée dans votre historique.",
                    badge="Sans alerte", style="quiet", quiet=True,
                    notification="Non envoyée", siren="Non demandée")
    rule = (metadata.get("regle") or {}).get("type", "")
    title = "Passage détecté" if rule == "line_crossing" else event.get_type_display()
    status = {"new": "À vérifier", "confirmed": "Intrusion confirmée", "false_alarm": "Fausse alerte"}
    grouped = event.notification_supprimee
    badge = status.get(event.statut, event.get_statut_display())
    if event.statut == "new" and event.priorite_alerte >= 100:
        badge = "À vérifier · Urgent"
    return dict(title=title, heading=status.get(event.statut, event.get_statut_display()),
                icon="eye", message="Consultez l’image pour comprendre ce qui s’est passé.",
                badge="Regroupé" if grouped else badge,
                style="neutral" if grouped else event.statut, quiet=False,
                notification="Pas de nouvel envoi" if grouped else "Selon vos préférences",
                siren="Pas de nouveau signal" if grouped else "Selon vos réglages")


@register.filter
def camera_summary(camera):
    if camera.statut_appairage == "revoked":
        return "Accès retiré"
    if camera.statut_appairage == "unpaired":
        return "À connecter"
    if not camera.est_connectee:
        return "Hors ligne"
    if not camera.surveillance_appliquee_le or camera.surveillance_active != camera.surveillance_appliquee:
        return "Mise à jour en cours"
    return "Surveillance active" if camera.surveillance_appliquee else "Surveillance en pause"
