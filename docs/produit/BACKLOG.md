# Backlog produit

Date : 22 septembre 2026. Tous les tickets ci-dessous sont **à faire**. Les priorités indiquent l’ordre de construction ; elles ne constituent pas des dates de livraison. Les dépendances représentent les conditions minimales avant intégration complète.

## L1 — Fondations produit

| ID | Travail | Dépendances | Critères de validation |
|---|---|---|---|
| PROD-001 | Registre des modèles et décisions techniques | Aucune | Pour chaque modèle : origine, version, empreinte, classes, licence des poids et données, matériel requis ; décider du mode de distribution et de la cible mobile |
| SEC-001 | MFA TOTP web et administration | Aucune | Inscription par QR, confirmation avant activation, secret chiffré, préauthentification bornée, aucune session privilégiée avant OTP, anti-rejeu et limite d’essais ; tester les voies d’inscription et d’administration |
| SEC-002 | Récupération MFA et gestion des sessions | SEC-001 | Codes hachés à usage unique consommés atomiquement, remplacement du facteur avec réauthentification, révocation des sessions, audit sans secret, scénario téléphone perdu validé |
| EVT-001 | Définir et implémenter le contrat d’événement v2 | Aucune | Plusieurs objets, modèle/version, observation/réception distinctes, schéma borné ; HMAC couvre tous les champs, vecteurs de test croisés ; compatibilité v1 et historique conservée |
| EVT-002 | Réception idempotente et boîte d’envoi durable | EVT-001 | Événement et travail à effectuer écrits dans la même transaction ; retransmission sans doublon ; panne avant/après envoi récupérable ; champs modifiés ou signature invalide refusés |
| OPS-001 | Base de validation et retrait de la simulation | Aucune | Exécuter les tests dans une base isolée, automatiser leur lancement, refuser les événements simulés côté serveur et les retirer de l’interface ; conserver seulement la lecture de l’historique existant |

Premier incrément conseillé : `SEC-001`, puis `SEC-002`, avec `PROD-001` et `EVT-001` pour préparer les lots suivants. Aucune migration de base de production n’est nécessaire au cadrage documentaire.

## L2 — Caméras et horaires

| ID | Travail | Dépendances | Critères de validation |
|---|---|---|---|
| CAM-001 | Sources caméra et identité de passerelle | EVT-001, PROD-001 | Distinguer webcam et RTSP ; caméra rattachée à la bonne maison ; credentials chiffrés/expurgés ; passerelle limitée à ses caméras et révocable |
| CAM-002 | Service d’acquisition RTSP et reconnexion | CAM-001 | Démarrage automatique du service, acquisition H.264 sur matériel réel, timeout et reconnexion bornés ; coupure/retour de caméra sans boucle excessive ni secret dans les logs |
| CAM-003 | Assistant ONVIF et qualification | CAM-002 | Découverte limitée au réseau autorisé, saisie manuelle alternative, test du flux et fiche modèle/firmware ; URL distante non autorisée refusée ; aucune compatibilité globale déduite d’une marque |
| SCH-001 | Plannings et dérogations | SEC-002 | CRUD autorisé et audité, fuseau par maison, passage de minuit, exceptions ; priorité manuelle et expiration testées, conflits déterministes |
| SCH-002 | Application autonome des horaires | SCH-001, CAM-002 | Planning signé/versionné localement, accusé de version et d’état appliqué, reprise au boot et sans Internet ; révocation prise en compte dès reconnexion ; aucun navigateur requis |
| CAM-004 | Tampon local et santé de l’analyse | EVT-002, CAM-002, SCH-002 | File chiffrée bornée, horodatage d’observation conservé, soumission fraîche signée ; politique d’alertes retardées ; panne du modèle distinguée d’une simple présence réseau |

La matrice et le protocole de qualification se trouvent dans [CAMERAS.md](CAMERAS.md).

## L3 — Animaux et situations observables

| ID | Travail | Dépendances | Critères de validation |
|---|---|---|---|
| AI-001 | Interface de modèles et détection multiclasse | EVT-001, PROD-001, CAM-002 | Conserver personnes, chiens et chats dans une scène ; boîtes/scores/classes vérifiés ; seuils par classe ; résultat indisponible explicite en cas d’échec du modèle |
| AI-002 | Suivi temporel et zones configurables | AI-001 | Zones et lignes normalisées, validation des coordonnées, suivi sur plusieurs images, durée fondée sur le temps ; mêmes événements possibles à différentes cadences vidéo |
| AI-003 | Règles de franchissement et présence prolongée | AI-002, SCH-002 | Rule ID, version, durée et zone dans chaque alerte ; tests des passages autorisés et hors horaire ; suivi d’une personne maintenu en présence d’un animal |
| AI-004 | Évaluation et calibration terrain | AI-003 | Jeu annoté séparé des données d’ajustement ; jour/nuit, ombres, pluie, occlusion ; précision/rappel par classe, fausses alertes par caméra-heure et charge CPU/RAM consignés |
| ALT-001 | Priorités et regroupement d’événements | EVT-002, AI-003 | Règles serveur explicables, regroupement par caméra/piste/règle/fenêtre, seuils configurables ; alerte urgente non masquée par une rafale d’animaux |

## L4 — Application et alertes mobiles

| ID | Travail | Dépendances | Critères de validation |
|---|---|---|---|
| API-001 | API utilisateur versionnée et sessions mobiles | SEC-002, EVT-001 | Contrat documenté ; MFA avant jetons, renouvellement rotatif, révocation par appareil ; tous les objets filtrés comme sur le web ; JWT caméra rejeté |
| MOB-001 | Application installable et connexion | API-001, PROD-001 | Build installable sur téléphone réel, connexion/MFA, reconnexion, déconnexion et stockage sécurisé ; capture d’erreur réseau compréhensible |
| MOB-002 | Parcours maisons, caméras et événements | MOB-001, API-001 | État demandé/appliqué visible, pagination de l’historique, capture autorisée, classement d’alerte et armement selon droits ; anciennes données identifiées hors ligne |
| PUSH-001 | Installations mobiles et canal push | MOB-001, EVT-002 | Enregistrement et rotation du token, permission demandée, déconnexion dissociant le compte ; jetons invalides supprimés ; retries bornés et erreurs consultables |
| PUSH-002 | Préférences et alertes contextualisées | PUSH-001, ALT-001, MOB-002 | Notifications par catégorie/caméra, confidentialité de l’écran verrouillé, plages silencieuses et règles d’urgence explicites ; doublons regroupés, lien profond sans contournement des droits |
| PILOT-001 | Recette complète sur site pilote | CAM-004, AI-004, PUSH-002, OPS-002 | 24 h mesurées, scénarios de coupure, parcours caméra → mobile → décision, seuils de la feuille de route évalués et anomalies tracées |

Les essais push distinguent premier plan, arrière-plan, app terminée, arrêt forcé, permissions refusées et économie d’énergie. Une acceptation par le fournisseur n’est pas un accusé de réception sur le téléphone. Les réglages du système peuvent limiter les alertes ; l’historique doit permettre leur rattrapage. [Documentation FCM](https://firebase.google.com/docs/cloud-messaging/flutter/receive-messages).

## L5 — Visages et armes

| ID | Travail | Dépendances | Critères de validation |
|---|---|---|---|
| FACE-001 | Profils volontaires et cycle de vie biométrique | SEC-002, PROD-001, OPS-002 | Inscription volontaire, droits par maison, stockage chiffré, audit, export/suppression ; retrait serveur immédiat, purge locale confirmée à reconnexion et expiration courte du cache interdisant les comparaisons sans renouvellement |
| FACE-002 | Comparaison faciale et résultat incertain | FACE-001, AI-001, MOB-002 | Profil de référence versionné, seuil testé, qualité insuffisante distincte d’un inconnu ; taux de fausse acceptation et de faux rejet documentés selon les conditions ; aucune commande d’accès déclenchée par le visage |
| WEAPON-001 | Sélection et évaluation du modèle spécialisé | PROD-001, AI-001 | Classes d’armes définies, données et poids utilisables, jeu d’évaluation indépendant ; téléphones, outils, jouets et couteaux domestiques inclus parmi les confusions à mesurer |
| WEAPON-002 | Alertes de suspicion d’arme | WEAPON-001, ALT-001, PUSH-002 | Seuils d’acceptation décidés avant évaluation finale, validation temporelle, capture/contextes et priorité expliquée ; libellé de suspicion, décision humaine et interruption indépendante du module |

`FACE-001` et `WEAPON-001` comprennent la vérification des droits d’utilisation et des conditions d’exploitation des données retenues. Cela fait partie de la conception des modules, sans imposer de collecte biométrique pour utiliser le reste du produit.

## Exploitation transversale

| ID | Travail | Dépendances | Critères de validation |
|---|---|---|---|
| OPS-002 | Rétention, sauvegarde et gestion des clés | EVT-002 | Durées explicites par donnée, purge de captures/événements/nonces/tampon, procédure de rotation, sauvegarde chiffrée et restauration testée avec déchiffrement des captures |
| OPS-003 | Déploiement permanent et supervision | CAM-004, PUSH-001 | Services ASGI/worker/ordonnanceur séparés, versions verrouillées, checks de dépendances, alerte sur absence d’image et retard de file ; logs sans URL ou secret caméra |
| OPS-004 | Validation d’exploitation | PILOT-001, OPS-003 | Liste des modèles/firmwares qualifiés, charge maximale mesurée, procédure de mise à jour et de retour arrière, guide d’installation et procédures d’incident |

## Règle de livraison

Pour passer un ticket à « terminé », fournir le changement, les migrations éventuelles, les tests pertinents et une preuve du parcours utilisateur. Les fonctions dépendant du matériel incluent la référence testée ; les modèles IA incluent leur rapport d’évaluation. Une interface affichant des données simulées ne valide ni une intégration caméra ni une notification réelle.

Une livraison peut être utilisable avant que les huit chantiers soient terminés. Le pilote L4 couvre la surveillance quotidienne ; les modules L5 sont activables séparément après validation.
