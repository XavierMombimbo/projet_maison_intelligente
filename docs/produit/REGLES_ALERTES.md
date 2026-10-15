# Règles explicables d’alerte

AI-003 ajoute deux règles locales sur les pistes d’AI-002 : présence prolongée dans la zone et franchissement de la ligne dans un sens interdit. Une alerte décrit un fait observé ; elle ne qualifie pas automatiquement une personne d’intruse.

## Règles

| Identifiant | Version | Déclenchement |
|---|---:|---|
| `presence-zone` | 1 | Une ou plusieurs pistes restent dans la zone pendant la durée configurée. |
| `line-crossing` | 1 | Une piste traverse la ligne dans le sens interdit configuré. |

La caméra peut interdire les deux sens, gauche vers droite ou droite vers gauche avec la ligne verticale proposée. Les pistes sont toujours associées séparément par classe : l’apparition d’un chien ne remplace donc pas la piste d’une personne.

Chaque événement transporte un contexte signé comprenant `id`, `version`, `type`, `duration_seconds`, `zone`, la ligne et la direction lorsqu’elles s’appliquent, ainsi que les `track_ids`. Le serveur valide les coordonnées et la structure, inclut ce contexte dans l’empreinte idempotente et l’affiche dans le détail de l’événement. Toute modification en transit invalide la signature HMAC.

Lorsque la surveillance est désactivée, notamment hors planning, le client n’exécute pas les règles et l’API refuse aussi l’événement. L’application autonome des changements de planning sur une caméra RTSP reste dans SCH-002, en attente du matériel.

## Priorité et regroupement

ALT-001 calcule la priorité sur le serveur. La caméra ne peut pas imposer ce niveau.

| Situation observée | Priorité |
|---|---|
| Personne franchissant la ligne | Urgente |
| Personne au-dessus du seuil | Élevée |
| Animal franchissant la ligne | Normale |
| Chien ou chat au-dessus du seuil | Faible |

Les seuils personne et animal se règlent par caméra. Le client les applique à l’analyse locale et le serveur les réutilise pour expliquer la priorité. Une répétition est regroupée lorsqu’elle vient de la même caméra, de la même piste et de la même version de règle pendant la fenêtre configurée. La fenêtre repart depuis la répétition la plus récente afin qu’une série continue reste rattachée à la même alerte principale. Tous les événements restent enregistrés avec leur capture, mais seule l’alerte principale crée une entrée dans la boîte d’envoi.

Une priorité supérieure n’est jamais absorbée par une alerte plus faible déjà présente dans la fenêtre. Ainsi, une personne franchissant la ligne reste notifiée même après une rafale d’événements animaux.

## Recette manuelle

1. Configurer la zone centrale et une durée de 3 secondes.
2. Activer la ligne verticale `50/0 → 50/100` et choisir **Dans les deux sens**.
3. Démarrer la webcam et passer lentement d’un côté à l’autre de la ligne : l’état du dernier événement doit indiquer **Franchissement envoyé**.
4. Rester immobile dans la zone après le délai de 15 secondes : une alerte **Présence prolongée** doit ensuite être possible après 3 secondes.
5. Ouvrir les événements et vérifier la carte **Règle déclenchée** avec l’identifiant, la version, la durée, la zone et la direction.
6. Désactiver la surveillance et repasser la ligne : aucun nouvel événement ne doit être créé.

### Recette du regroupement

1. Dans **Configurer la détection**, choisir une fenêtre de regroupement de 60 secondes.
2. Ouvrir le mode caméra et franchir la ligne deux fois avec la même piste, en laissant passer le délai local entre les deux événements.
3. Vérifier dans l’historique que l’alerte principale indique deux événements regroupés.
4. Ouvrir le second événement : il doit indiquer qu’aucune notification supplémentaire n’a été envoyée.
