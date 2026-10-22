# Suspicion d’arme — essai web du 20 octobre 2026

## Surveillance combinée — 22 octobre 2026

La demande utilisateur réunit intrusion et arme dans Mode caméra, avec un seul
Démarrer / Arrêter et le message **Personne détectée avec port d’arme probable**.
Activation distincte : `WEAPON_COMBINED_ENABLED=True`, désactivée par défaut,
avec les mêmes droits, liste de caméras autorisées et horaires que l’intégration
académique existante. Aucun démarrage automatique. Les modèles et leur registre
restent inchangés : le mode review utilise toujours un modèle expérimental,
sans prétendre à une qualification de précision ni à une preuve de menace.

Les deux modèles lisent le même instantané figé : personnes/animaux dans le
navigateur, armes sur le serveur. La signature couvre capture, objets, règle et
session d’analyse ; seules des classes ordinaires sont acceptées du navigateur.
Les classes/boîtes d’armes et leur confirmation sont exclusivement calculées
par le serveur. Trois observations cohérentes sur au moins deux secondes sont
requises. L’association personne/objet est évaluée sur chaque image : personne
au-dessus du seuil et dans la zone, au moins 60 % de la boîte de l’objet près de
sa boîte légèrement étendue. Une arme seule ou éloignée ne permet pas d’afficher
un port probable : le libellé reste alors **Suspicion d’arme**.

Un même événement réunit personne, objet et capture chiffrée. Contrairement à
l’ancien essai isolé, ce mode explicitement activé utilise les événements
habituels, la boîte d’envoi et les notifications contextualisées. Les images
intermédiaires ne sont pas conservées. Le message est commun à la fiche, aux
alertes web et au push ; la visibilité personnelle de l’écran verrouillé reste
respectée. Une personne connue reste silencieuse en l’absence d’arme ; une arme
probable peut justifier une notification même si le visage est reconnu.

Un candidat proche retient la présence ordinaire au maximum 4,5 secondes pour
éviter deux notifications immédiates. Un franchissement n’est jamais retardé.
Les événements ordinaires sont espacés d’au moins 15 secondes ; les suspicions
répétées d’au moins 30 secondes, avec regroupement serveur habituel. Une suspicion
associée à une personne peut relever une précédente arme seule. Une panne du
modèle d’arme conserve le chemin d’intrusion ; une panne de l’API combinée reprend
le même événement/capture sur l’API ordinaire, sans fabriquer une preuve d’arme.
Arrêt, changement de compte, retrait des droits et horaires interrompent les
analyses et invalident les réponses tardives. Les horaires sont revérifiés après
les inférences avant stockage. Les nouvelles ressources mobiles nécessitent
une mise à jour de l’application pour l’affichage au premier plan.

**Interface simplifiée le 21 octobre :** deux boutons « Démarrer » et
« Arrêter », état « Arrêté », panneau de résultat compact et vidéo sur toute
la largeur. Les explications sont repliées dans « Informations ». L’envoi
d’images au serveur reste annoncé avant le démarrage et le mode académique
reste indiqué. Horaires, permissions, signature et événements sont inchangés.

Cartes existantes : [WEAPON-001](https://trello.com/c/Xbn4vKsm) et
[WEAPON-002](https://trello.com/c/vSAzFbqu). Portée demandée : armes à feu et
couteaux, d’abord dans **Mode caméra**. Ce lot prépare une recette explicite ;
il ne qualifie pas un détecteur et n’active aucune alerte en production.

## Intégration au site académique habituel

Le lot local reste validé. Une activation distincte permet de proposer la même
démonstration depuis **Mode caméra** sur le site habituel, avec connexion et
droits de pilotage existants. Cette intégration est désactivée par défaut :

```dotenv
WEAPON_DETECTION_MODE=review
WEAPON_MODEL_ROOT=CHEMIN_PRIVE_DU_MODELE_VERIFIE
WEAPON_ACADEMIC_SITE_ENABLED=True
WEAPON_ACADEMIC_SITE_CAMERA_IDS=UUID_CAMERA_AUTORISEE
```

La liste contient des UUID séparés par des virgules. Seules ces caméras, pour
un utilisateur ayant déjà leurs droits de pilotage, proposent **Démarrer la
démo**. Les autres caméras ne proposent pas le test et l’API refuse leurs
requêtes avant inférence. Une liste vide, un identifiant invalide, l’absence
de consentement signé ou des droits retirés ne permettent pas d’enregistrer
d’événement. Mode et droits/liste sont revérifiés après l’inférence.

Les requêtes ordinaires `weapon-observation` ne permettent pas de contourner
le parcours explicite lorsque le site académique est activé. Ce mode réutilise
les événements expérimentaux sans image/outbox, exclus de l’opérationnel, même
si les notifications ordinaires du site restent activées. Il n’exige pas de
désactiver FCM pour les autres événements, de passer DEBUG à true, de changer
de base ou de contourner la connexion. Le bootstrap fictif `/review/` et son
alias `/connexion/` restent uniquement dans le lanceur local non publié.

Le modèle conserve `evaluation_only` ; `alerts` reste verrouillé. Ni les poids,
ni les bases, captures ou paramètres privés ne sont inclus dans la source.
OpenCV headless est déclaré dans les dépendances serveur, comme sur la
passerelle. L’utilisateur a demandé la mise en ligne le 21 octobre, sans refaire
les démonstrations déjà validées. Après vérification dans Chrome et accord
explicite, la caméra appairée « vue exterieure » est la cible du site habituel.
Depuis le lien général Mode caméra,
un choix explicite ouvre la caméra autorisée sans modifier l’appairage local.
La démo respecte les horaires de surveillance de la maison, conformément au
choix explicite de l’utilisateur le 21 octobre. Hors horaires, l’analyse reste
en pause. Le planning et l’arrêt manuel de la caméra ne sont pas modifiés.

Le déploiement utilise une source isolée issue de la version V10 publiée,
avec seulement les changements de suspicion d’arme et leur documentation.
Le superviseur accepte `SourceRoot` (source vérifiée) et `RuntimeRoot`
(environnement Python et configuration de tunnel existants). La base et les
clés privées restent dans ProductionHome ; les travaux partagés ne sont pas
écrasés. Aucun lancement automatique de webcam n’accompagne l’activation.

## Démonstration académique avec événement d’essai

**Recette complète validée le 21 octobre 2026 :** captures utilisateur montrant
le couteau repéré, l’avis d’événement enregistré puis sa fiche ouverte. Événement
`5b1d3e89-80c3-4565-ad40-1856a1f98836` vérifié en lecture seule : knife/suspected,
academic_weapon_demo=true, simule=true, notifications externes supprimées,
aucune capture ni boîte d’envoi. WEAPON-002 Terminée pour cette démonstration
locale. Cette validation ne constitue pas une mesure indépendante de précision.
Le refus du rejeu de la capture reste respecté ; ce résultat provient de la
webcam démarrée volontairement par l’utilisateur, sans rejeu de l’agent.

L’utilisateur a rappelé le cadre académique déjà confirmé. La démonstration
peut avancer avec des événements explicitement expérimentaux, tout en gardant
les limites du modèle dans le rapport. La qualification d’alertes réelles ne
conditionne pas cette démonstration isolée.

**Parcours simplifié le 21 octobre :** ouvrir
[la démonstration académique](http://127.0.0.1:8774/review/), cliquer sur
**Démarrer la démo**, montrer une image ou un objet factice et
attendre la suspicion répétée. Un encadré « Alerte d’essai enregistrée —
expérimental » donne accès à la fiche dans un autre onglet ; arrêter la webcam
avant de quitter le test. Sur cette instance académique isolée, un seul bouton
lance détection et alerte d’essai ; il n’y a plus de second démarrage à choisir.
L’indication « Alerte d’essai activée pour cette démo » annonce ce comportement.
La revue ordinaire reste distincte sur l’ancienne instance 8773.

Le choix académique est couvert par la signature HMAC via le nom de modèle
`weapon-observation-academic-demo`. Le serveur applique la confirmation réelle
du modèle en mode review, trois observations sur au moins deux secondes et
un intervalle minimal de 30 s entre événements. Il stocke uniquement un
événement `simule=True`, les classes/boîtes/scores et l’empreinte de l’observation,
sans image ni boîte d’envoi. Ces événements sont exclus des événements
opérationnels ; leur fiche annonce l’essai, n’affiche pas d’image absente et
ne propose pas de confirmer une intrusion. L’avis est affiché sur l’écran du
test ; aucun push, courriel, son ou message externe n’est déclenché.

Activation réservée au lanceur local : caméra explicitement désignée dans
`WEAPON_ACADEMIC_DEMO_CAMERA_IDS` (vide/absent par défaut), DEBUG, SQLite,
FCM désactivé et adresse cliente de boucle locale. Vérification avant et après
inférence ; session, CSRF, droits et anti-rejeu habituels restent requis.
Le registre reste `evaluation_only` ; le mode `alerts` garde son verrou.
Le caractère académique n’est pas présenté comme une résolution automatique
des divergences documentaires, ni comme une mesure de fiabilité.

Le lanceur `tmp/run_weapon_demo.py --port 8774` utilise une nouvelle base et
de nouveaux cookies sous `tmp/weapon-academic-demo-20261020/`, sans interrompre
l’ancienne instance 8773. Aucun compte ni donnée de production copié. Le lanceur
et ces données sont des fichiers locaux de recette, hors source publiée.
Sur ce seul lanceur, `/connexion/` ouvre également le compte fictif via le
bootstrap : pas de formulaire de mot de passe pour la démo. La méthode GET et
l’adresse loopback sont requises ; aucune connexion de production n’est changée.

## Qualification — reprise après validation utilisateur

L’utilisateur a confirmé « ça marche » pour le lot local armes à feu/couteaux.
La recette de base est acceptée. La qualification de WEAPON-001 reprend sans
changer le modèle actif ni autoriser d’alerte réelle.

Revue des sources officielles le 20 octobre 2026 :

| Source | Constat | Décision pour cette étape |
|---|---|---|
| [ECE, fiche du candidat](https://huggingface.co/ECE-Software/connect-t1-weapon-fp32) | Métadonnées Hub toujours Apache-2.0, sans README supplémentaire renvoyé par le connecteur ; ONNX épinglé déclarant AGPL-3.0 et chemin Kaggle sans inventaire de sources | Garder `evaluation_only` ; demander à l’auteur la licence exacte des poids et l’inventaire des données avant qualification |
| [DISARM, auteurs](https://deepknowledge-us.github.io/DISARM-dataset/) | Sous-ensemble de test issu de quatre vidéos, usage académique annoncé CC BY-NC 4.0 ; lien de téléchargement renvoyant vers connexion Microsoft lors de la vérification | Candidat de test académique, pas un modèle de remplacement ; accès et indépendance à établir, aucun jeu téléchargé |
| [OD-WeaponDetection, README](https://github.com/ari-dasci/OD-WeaponDetection) / [License.md](https://github.com/ari-dasci/OD-WeaponDetection/blob/master/License.md) | README annonce CC BY-SA 4.0 ; fichier License.md contient CC BY 4.0 | Corriger l’ancienne mention de licence unique : divergence à clarifier avant réutilisation ; pas de téléchargement |
| [CostiCatargiu, section licence](https://github.com/CostiCatargiu/Yolov12_WeaponDetection#%EF%B8%8F-license) | Données et poids réservés à la recherche ; images de vidéos publiques, code également limité à la recherche | Ne pas substituer ce modèle pour débloquer des alertes ; provenance et validation sur matériel cible restent requises |

Ces constats décrivent les documents disponibles ; ils ne constituent pas une
conclusion juridique sur des droits absents. Aucun message envoyé aux auteurs.
Demande prête à transmettre à l’auteur ECE : confirmer la licence applicable à
`model.onnx` de la révision `c7a093b53e59ce25abac9d35aa4fc1122915832f`, expliquer
la divergence Apache/AGPL, fournir sources/licences et répartition des images
d’entraînement/validation/test, et préciser les éventuels jeux publics inclus.

### Protocole proposé `weapon-pilot-v1` — à accepter avant évaluation finale

Les seuils d’inférence restent firearm 0,65 et knife 0,70. Les objectifs
ci-dessous sont des propositions de conception pour un pilote de revue
humaine, pas des normes de sûreté ni des performances acquises. Une fois le
protocole accepté, figer modèle, empreintes, seuils et répartition des scènes ;
un ajustement ultérieur exige un autre jeu de test final.

| Mesure | Proposition avant pilote |
|---|---|
| Détection des objets | Précision ≥ 95 % et rappel ≥ 90 % par classe, boîtes appariées une à une à IoU ≥ 0,50 ; publier effectifs et incertitude |
| Confirmation temporelle | Rappel ≥ 90 % par classe sur ≥ 100 épisodes d’au moins 6 s, issus d’au moins 20 scènes distinctes par classe ; jour/faible lumière, distance et occultation représentés |
| Confusions ordinaires | Mesurer séparément téléphone, outil, jouet, scène vide ; une suspicion répétée lors de la recette courte impose analyse avant poursuite |
| Couteau domestique et image d’arme | Annoter l’objet visible et le contexte séparément : un couteau correctement détecté n’est pas une erreur de boîte ; compter aussi les avertissements inutiles selon l’usage attendu. Le modèle ne connaît pas l’intention. Aucune exemption domestique ni preuve de menace déduite de sa classe |
| Fausses alertes temporelles | Objectif proposé ≤ 0,1 par caméra-heure ; à zéro fausse alerte, au moins 30 h de vidéo négative donnent une borne supérieure Poisson unilatérale 95 % d’environ 0,10/h. Publier durée par contexte et scènes ; quelques minutes sans erreur ne suffisent pas |
| Latence | p95 caméra → résultat ≤ 5 s sur le matériel et le réseau cibles ; mesurer aussi charge CPU/mémoire et erreurs. Le temps d’inférence seul ne valide pas ce critère |
| Droits et indépendance | Documents des poids/données et absence de recouvrement entraînement/test établis ; une liste déclarative de scènes ne constitue pas une vérification |

Les exemples image/vidéo publics peuvent servir d’exploration après revue de
leurs droits ; tant que l’entraînement du candidat est inconnu, ne pas appeler
ce test « indépendant ». Des captures d’écran et images uniformes ne qualifient
pas un système de surveillance. La sirène et l’activation publique restent une
étape distincte après droits, métriques et validation utilisateur.

**Recette courte suivante, en mode review existant :** présenter successivement
un téléphone, un stylo et une main vide, environ 10 secondes chacun ; le résultat
attendu est « Aucune suspicion sur cette image ». Relever toute apparition de
« Objet à vérifier » ou « Suspicion d’arme », puis arrêter. Cette recette explore
les confusions ; elle ne remplace pas les mesures annotées ci-dessus.

## Comportement livré

- Le module est désactivé par défaut (`WEAPON_DETECTION_MODE=disabled`).
- Sur une instance de recette configurée en `review`, cliquer sur **Démarrer
  le test** : ce clic sélectionne l’essai et demande l’ouverture de la webcam.
  Aucune ouverture ni capture supplémentaire avant ce clic ; une image toutes
  les 1,5 seconde ensuite, lorsque la surveillance est active. Le résultat est
  affiché en grand : « Aucune suspicion sur cette image », « Objet à vérifier »
  ou « Suspicion d’arme ». Les réglages et explications sont repliés.
- Le serveur effectue l’inférence ; le navigateur ne fournit jamais un résultat
  d’arme. Les candidats sont entourés avec « Arme à feu ? » ou « Couteau ? ».
- Trois observations distinctes, sur au moins deux secondes, doivent concerner
  la même classe et des boîtes qui se recouvrent (IoU ≥ 0,30). Une absence ou
  un écart de plus de trois secondes réinitialise la confirmation. Les requêtes
  rapprochées et les reprises du même identifiant ne constituent pas de preuves
  supplémentaires. Ce suivi de boîtes n’identifie pas une personne.
- Une suspicion répétée est affichée comme un objet **à vérifier**, sans
  conclusion sur l’intention. Un couteau domestique reste un risque de fausse
  alerte : le modèle ne détermine pas son usage.
- En `review` ordinaire, aucune image intermédiaire, aucun événement ni aucune alerte
  d’arme ne sont conservés. La surveillance habituelle conserve son comportement.
  **Arrêter le test** ferme la webcam et coupe les prochains envois ; un résultat arrivé
  tardivement est ignoré. Un redémarrage crée une nouvelle session d’analyse.
- Une défaillance du module reste distincte d’une image sans candidat et
  n’arrête pas la détection habituelle ou la reconnaissance faciale.

## Contrôles serveur

`POST /api/camera/me/suspicion-arme/` réutilise le JWT caméra lié à la session
web, les droits de commande, le CSRF et une signature HMAC v2 couvrant le chemin,
l’UUID, l’horodatage et le SHA-256 de l’image. Le corps signé décrit uniquement
une observation `scene`, modèle `weapon-observation`, version UUID de session.
Un résultat client, une session autonome, une signature incorrecte et une
observation de plus de cinq secondes sont refusés. Limite : 45 appels/minute/caméra.
Les droits et la surveillance sont revérifiés après l’inférence. Les réponses
sont privées et sans cache ; l’état temporel ne contient que boîtes, scores,
temps et identifiants de requêtes, avec expiration après 90 secondes d’inactivité.
Une panne du cache ne doit pas être interprétée comme une absence d’arme.

Le chemin `alerts` est préparé mais refuse le candidat actuel : seul un artefact
`production_approved` peut charger ce mode. Une confirmation serveur crée alors
un événement avec capture chiffrée, priorité urgente expliquée, regroupement,
délai minimal de 30 secondes, boîte d’envoi et préférences push existantes.
Une présence reconnue ne supprime pas cette suspicion. Le libellé reste une
suspicion ; la confirmation et la fausse alerte sont des décisions humaines.
Cette branche a été testée avec des résultats synthétiques, pas sur le terrain.

## Artefact évalué techniquement, non qualifié

Source : [ECE-Software/connect-t1-weapon-fp32](https://huggingface.co/ECE-Software/connect-t1-weapon-fp32),
révision `c7a093b53e59ce25abac9d35aa4fc1122915832f`.

| Propriété | Valeur vérifiée |
|---|---|
| Fichier | `model.onnx`, 12 268 102 octets, hors source publiée |
| SHA-256 | `d300e36bb5c1939e0ca0717e7523fcee93d8a4cb502ec407e21f596d26935068` |
| Entrée / sortie | float32 `[1,3,640,640]` / `[1,8,8400]` |
| Classes exactes | 0 Gun, 1 explosion, 2 grenade, 3 knife |
| Classes retenues | 0 → firearm, 3 → knife ; explosion/grenade exclues |
| Seuils de développement | firearm 0,65 ; knife 0,70, sans validation terrain |
| Licence | Fiche Apache-2.0, métadonnées ONNX AGPL-3.0 : divergence non résolue |
| Entraînement déclaré dans ONNX | `/kaggle/input/threat-detection-3849/data.yaml`, provenance et droits non établis |
| Statut | `evaluation_only`, aucune approbation de production |

Un essai CPU avec deux threads sur trois images synthétiques uniformes a pris
94,55 / 99,62 / 120,56 ms après échauffement ; aucun candidat retenu. Il vérifie
le chargement et le format de sortie, **pas la précision**, le rappel ou le
débit d’une webcam. Le cache local de cette session est
`tmp/weapon-review-20261020`, ignoré par Git. Aucune webcam ni image réelle
n’a été utilisée par l’agent.

Autres sources relues : [DISARM officiel](https://deepknowledge-us.github.io/DISARM-dataset/)
(test académique CC BY-NC 4.0), [CostiCatargiu](https://github.com/CostiCatargiu/Yolov12_WeaponDetection)
(poids et données limités à la recherche, images de sources publiques) et
[seif744](https://github.com/seif744/Weapon_Detection) (provenance et faux positifs
encore insuffisants). Aucun de ces travaux n’est qualifié ici pour le pilote.

## Recette proposée

**Instance locale prête pour cette session :**
[ouvrir la recette](http://127.0.0.1:8773/review/).
Le lanceur `tmp/run_weapon_demo.py` crée une base distincte sous
`tmp/weapon-demo-20261020/`, une maison et un compte fictifs sans mot de passe
utilisable. Une entrée de démonstration réservée à l’adresse de boucle locale
ouvre ce seul compte ; elle n’est ni un parcours produit ni un composant publié.
Les cookies de session/CSRF sont distincts de ceux de la production, FCM et
reconnaissance faciale sont désactivés sur cette instance. La webcam exige
toujours un clic de l’utilisateur. Cet environnement est limité à `127.0.0.1` ;
ne pas utiliser son lanceur en production. Son dossier est ignoré par Git.

Un contrôle HTTP réel a envoyé une seule image grise générée en mémoire via
cette instance : session, CSRF, HMAC et inférence ONNX, **200/clear/review**,
aucun événement ni demande de notification d’arme. Ce n’est pas une recette
webcam ni une mesure de précision. La surveillance habituelle peut créer ses
propres événements locaux de personnes ; les alertes d’arme restent séparées.

Pour relancer cette instance après fermeture du processus :

```powershell
$env:PYTHONPATH=(Get-Location).Path
.\.venv\Scripts\python.exe tmp/run_weapon_demo.py
```

Sur une **instance de recette distincte de la production**, configurer le chemin
du dossier contenant le fichier vérifié et `WEAPON_DETECTION_MODE=review`.
Utiliser un compte et une caméra de recette ; conserver la passerelle autonome
arrêtée si elle partage la webcam. Ne pas réenrôler de visage.

1. Ouvrir Mode caméra, cliquer sur **Démarrer le test** et autoriser la webcam
   si le navigateur le demande. Ce seul bouton lance webcam et essai.
2. Lire le résultat dans le grand encadré au-dessus de la vidéo. Les erreurs
   de permission y sont aussi indiquées, avec une action pour réessayer.
3. Vérifier les états et les boîtes avec un support d’essai inerte ; mesurer
   aussi les confusions avec téléphone, outil, jouet et couteau domestique.
4. Cliquer sur **Arrêter le test** : webcam fermée, plus de nouvel envoi et
   résultats tardifs ignorés, y compris si l’autorisation était encore en attente.
5. Vérifier que le module n’a créé ni événement ni notification d’arme.

L’aperçu `tmp/preview_weapon_review.py`, sur `http://127.0.0.1:8772/`, montre
uniquement la mise en page synthétique. Il supprime les scripts et refuse POST :
il ne permet pas cette recette fonctionnelle et ne demande aucune webcam.

## Évaluation indépendante à fournir avant activation

Fixer les seuils d’acceptation avant l’évaluation finale. Séparer les scènes et
vidéos d’entraînement, d’ajustement et de test ; ne pas répartir des images
voisines d’une même vidéo entre ces groupes. Inclure jour/nuit, occultations,
distance, téléphone, outils, jouets, couteaux domestiques et scènes sans arme.
Mesurer par classe précision/rappel des boîtes, rappel des épisodes temporels,
fausses alertes par caméra-heure, latence et charge CPU/mémoire. L’absence
d’annotations ou de provenance n’est pas un résultat favorable.

Un outil local prépare les métriques de **détection** :

```powershell
.\.venv\Scripts\python.exe -m gateway.weapon_evaluation --model-root DOSSIER_MODELE --manifest DOSSIER_TEST\manifest.json --output rapport-arme.json
```

Exemple de manifeste, à compléter avec des images autorisées et annotées :

```json
{
  "protocol_id": "identifiant-du-protocole-fige",
  "training_source_groups": [],
  "images": [{
    "file": "image.png", "source_group": "scene-independante-001",
    "context": "phone", "alert_expected": false, "objects": []
  }]
}
```

`objects` contient des boîtes normalisées `{label, bbox:[x,y,width,height]}`
pour `firearm` ou `knife`. Les contextes autorisés sont `firearm`, `knife`,
`phone`, `tool`, `toy`, `household_knife`, `clean`. Un couteau domestique peut
être une vraie boîte `knife` tout en ayant `alert_expected=false` : ces deux
mesures ne doivent pas être confondues. L’outil refuse les chemins hors dossier,
doublons et scènes déclarées communes avec l’entraînement. Il conserve
`production_qualified=false`, même si un petit jeu affiche de bons chiffres ;
les droits, la provenance et les mesures vidéo restent à établir.

Le rapport inclut maintenant l’empreinte SHA-256 du manifeste et de chaque
image (fichier et pixels décodés), refuse les copies identiques renommées ou
réencodées sans changement de pixels, et donne moyenne/maximum du temps
d’inférence, première inférence incluse. Les presque-doublons, recadrages et
fuites d’entraînement inconnues ne sont pas détectés automatiquement.
`training_provenance_declared` reste distinct de `independence_verified=false`.
Ce rapport ne calcule ni rappel temporel, ni fausses alertes par heure, ni
latence réseau. Aucun bon résultat de cet outil ne débloque `alerts`.
