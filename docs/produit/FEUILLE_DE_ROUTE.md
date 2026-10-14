# Sentinelle Maison — feuille de route produit

Date de cadrage : 22 septembre 2026. Statut : plan de développement, aucune des nouvelles capacités ci-dessous n’est déclarée livrée.

## Objectif

Faire évoluer le socle web vers une solution utilisable au quotidien : surveillance autonome de caméras réelles, alertes utiles sur téléphone et contrôle sécurisé des accès. Le nom de travail reste **Sentinelle Maison**. Les documents académiques existants restent des archives ; ils ne fixent plus le périmètre du produit.

Le premier pilote proposé couvre une maison, une à deux caméras et les utilisateurs autorisés. Android est la cible initiale proposée, avec une architecture mobile compatible iOS. Le modèle de caméra, le matériel de calcul, la cible mobile définitive et le budget d’exploitation restent à préciser. Ce sont des hypothèses de travail, pas des achats ni des engagements de délai.

## Point de départ vérifié dans le dépôt

| Domaine | Existant | Écart à combler |
|---|---|---|
| Comptes | Sessions Django, Argon2, limitation de débit, journal d’audit | MFA, récupération de compte et sessions mobiles révocables |
| Maisons et accès | Propriétaire, membres, permissions par caméra | Étendre les mêmes contrôles aux nouvelles API, données biométriques et notifications |
| Acquisition | Webcam autorisée depuis le navigateur, appairage et identité caméra révocable | Caméras IP et service autonome |
| Vision | YOLO11n 320, COCO-SSD en secours, classes `person`, `dog` et `cat` | Suivi temporel, zones, visages et modèle spécialisé pour armes |
| Événements | Capture chiffrée, requête signée, anti-rejeu, plusieurs objets et provenance du modèle | Règles contextuelles et regroupement |
| Alertes | WebSocket et sirène web facultative | Push mobile, préférences, reprises de livraison et accusés de lecture |
| Surveillance | Activation manuelle, planning quotidien, fuseau et exceptions | Reprise autonome après redémarrage et état réellement appliqué sur une caméra RTSP |
| Exploitation | ASGI, configuration PostgreSQL/Redis et endpoint `/health/` | Travailleurs persistants, sauvegarde/restauration, supervision et validation terrain |

Constats issus de `accounts/views.py`, `homes/models.py`, `homes/detection.py`, `homes/request_signing.py`, `homes/realtime.py`, `config/settings.py` et `static/js/camera-monitor.js`. Les seuils sont 0,45 pour une personne et 0,50 pour un chien ou un chat, avec une seule image requise et 15 secondes entre événements. Le contrat v2 transporte plusieurs objets et leur classe, mais pas encore d’identité faciale ni de règle de comportement. Cet état des lieux est une lecture du code, pas une mesure de fiabilité en situation réelle.

## Les huit fonctionnalités demandées

| N° | Fonctionnalité | Première version utile | Validation attendue |
|---|---|---|---|
| 1 | Reconnaissance faciale | Profils volontaires par maison ; résultat « personne connue », « personne non reconnue » ou « visage inexploitable » | Inscription et suppression complètes, isolation entre maisons, seuil de correspondance évalué, absence de désarmement automatique |
| 2 | Reconnaissance des animaux | Détection de chiens et chats ; classes supplémentaires selon les besoins terrain | Personne et animal simultanés correctement conservés, réglages par caméra, résultats mesurés de jour et de nuit |
| 3 | Mouvements suspects et armes | Franchissement d’une ligne, entrée en zone surveillée, présence prolongée ; suspicion d’arme via un détecteur spécialisé | Chaque alerte explique sa règle ; arme présentée comme suspicion ; faux positifs et événements manqués mesurés séparément |
| 4 | Démarrage automatique | Planning hebdomadaire, périodes traversant minuit, exceptions et priorité manuelle temporaire | Fonctionnement navigateur fermé sur la passerelle, reprise après coupure, état demandé distinct de l’état appliqué |
| 5 | Application mobile | Connexion/MFA, maisons, caméras, état de surveillance, événements, captures et décisions | Installation sur téléphone réel, parcours complets, droits identiques au web, comportement réseau dégradé |
| 6 | Caméras réelles | Caméras IP qualifiées, flux RTSP et découverte/configuration ONVIF lorsque disponible | Modèle et firmware testés, reconnexion automatique, état hors ligne fiable et absence de secret caméra côté mobile |
| 7 | Alertes intelligentes mobiles | Priorités expliquées, regroupement, préférences et ouverture directe de l’événement | Push testé sur téléphone, reprise après panne, absence de doublons visibles et accès revérifié à l’ouverture |
| 8 | Authentification multifacteur | Mot de passe + TOTP, codes de récupération, gestion des appareils | Aucun accès protégé avant le second facteur, récupération sécurisée, révocation et limites d’essais vérifiées |

Reconnaître la catégorie « chien » ne signifie pas reconnaître individuellement le chien du propriétaire. Cette identification individuelle n’entre pas dans la première version animaux. Une personne non reconnue n’est pas automatiquement classée comme intruse.

## Ordre de livraison

L’ordre suit les dépendances techniques ; les numéros ci-dessus restent ceux de la demande initiale.

| Lot | Résultat livrable | Fonctionnalités concernées | Condition de sortie |
|---|---|---|---|
| L1 — Fondations produit | MFA web, contrat d’événement v2, traitement fiable et choix des modèles/licences | 8 ; fondations de 1, 2, 3, 5 et 7 | Parcours MFA validé ; anciens événements lisibles ; contrat v1 compatible ; reprise de traitement testée |
| L2 — Surveillance autonome | Passerelle, caméra IP pilote, planning et état de santé | 4 et 6 | Surveillance planifiée navigateur fermé ; essai continu de 24 h et scénarios de coupure réussis |
| L3 — Analyse contextualisée | Personnes/animaux, zones, suivi et règles explicables | 2 et première partie de 3 | Jeu d’évaluation annoté, seuils documentés, alerte animale ne masquant pas une personne |
| L4 — Pilote mobile | API mobile, application, push et traitement des alertes | 5 et 7 | Parcours réel caméra → événement → téléphone → décision ; MFA et permissions conservées |
| L5 — Reconnaissance avancée | Visages volontaires et détection spécialisée d’armes | 1 et seconde partie de 3 | Chaque module passe son évaluation et peut être désactivé séparément |

Le travail mobile peut commencer après stabilisation de l’authentification et du contrat API, avec des événements de test isolés. Le pilote complet attend la caméra réelle. Les recherches de modèles faciaux et d’armes commencent en L1 ; leur activation dépend des résultats, pas d’une simple intégration de bibliothèque.

## Expérience attendue

Le propriétaire ajoute une caméra, vérifie son image, définit les zones et choisit les horaires. À l’heure prévue, la passerelle applique la surveillance et confirme son état. Une personne franchissant une zone configurée génère un événement contextualisé. Le téléphone reçoit une alerte, puis affiche la capture après authentification ; l’utilisateur peut reconnaître une fausse alerte ou confirmer l’incident.

Exemples de messages visés : « Personne détectée dans la cour pendant la surveillance de nuit », « Chat détecté dans le jardin » et « Objet ressemblant à une arme : vérifiez la capture ». Le score du modèle reste une mesure de détection ; il ne remplace pas la priorité de l’alerte ni la décision de l’utilisateur.

## Conditions du premier pilote

Les valeurs suivantes sont des objectifs initiaux de recette, à mesurer sur le matériel retenu, et non des performances déjà obtenues.

| Mesure | Objectif initial | Méthode |
|---|---|---|
| Continuité | 24 h sans intervention sur 1–2 caméras | Journal du flux, de l’analyse et des redémarrages |
| Planning connecté | Transition appliquée en moins de 60 s | Comparaison de l’heure prévue avec l’accusé de la passerelle |
| Alerte mobile en conditions nominales | 95e percentile inférieur à 10 s | Horodatages observation, serveur, envoi et réception sur téléphone de test |
| Reprise réseau | Événements conservés dans la limite du tampon, sans doublon métier | Coupure contrôlée puis synchronisation ; événements anciens signalés comme retardés |
| Qualité de détection | Rapport par classe et par condition ; seuils retenus avant activation | Précision, rappel, fausses alertes par caméra-heure, latence et échecs d’analyse |
| Accès | Aucun accès accepté hors des droits prévus | Tests intermaisons, caméra révoquée, facteur invalide et appareil mobile retiré |
| Restauration | Base et captures restaurées dans un environnement vierge | Exercice de restauration incluant les clés nécessaires au déchiffrement |

Les seuils d’acceptation spécifiques aux visages et aux armes seront fixés avant l’évaluation finale, sur un jeu distinct des données d’ajustement. Aucun pourcentage universel de « précision IA » n’est annoncé.

## Travail immédiatement prêt

Commencer par les tickets `PROD-001`, `SEC-001`, `EVT-001` et `OPS-001` du [backlog](BACKLOG.md). Chaque livraison doit mettre à jour son statut avec une preuve de validation. La documentation actuelle organise le travail ; elle n’ajoute ni application mobile ni service de surveillance au déploiement.
