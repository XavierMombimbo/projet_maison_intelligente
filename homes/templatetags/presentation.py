"""Human-readable summaries; never infer delivery or identity from a score."""
from django import template

register = template.Library()


@register.filter
def event_summary(event):
    metadata = event.metadonnees or {}
    quiet_presence = bool(event.notification_supprimee and
                          metadata.get("alerte", {}).get("notification_supprimee"))
    if quiet_presence:
        return dict(title="Présence détectée", heading="Personne reconnue", icon="person-check",
                    message="La présence a été enregistrée dans votre historique.",
                    badge="Sans alerte", style="quiet", quiet=True,
                    notification="Non envoyée", siren="Non demandée")
    rule = metadata.get("regle", {}).get("type", "")
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
