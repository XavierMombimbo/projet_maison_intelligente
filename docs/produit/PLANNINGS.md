# Plannings de surveillance

SCH-001 définit la décision de surveillance d’une maison. Toutes les heures saisies et affichées utilisent le fuseau IANA enregistré sur la maison.

Le parcours principal demande seulement une heure d’activation et une heure d’arrêt. Ces horaires s’appliquent automatiquement aux sept jours. Si l’heure d’arrêt est antérieure à l’heure d’activation, l’arrêt a lieu le lendemain. Les plages par jour, exceptions et priorités manuelles restent disponibles dans « Options avancées ».

## Ordre de décision

1. Une priorité manuelle non expirée gagne.
2. Sinon, une exception datée active gagne. En cas de chevauchement, la priorité numérique la plus élevée gagne ; à égalité, la plus récente gagne.
3. Sinon, une plage hebdomadaire correspondante demande l’activation.
4. Hors de ces règles, la surveillance est arrêtée.

Une plage dont l’heure de fin est antérieure à l’heure de début traverse minuit. Par exemple, lundi 23:00–01:00 reste active jusqu’au mardi à 01:00.

## Application par la passerelle (SCH-002 en cours)

L'API d'etat camera calcule maintenant `monitoring_active` a chaque lecture.
Si la maison possede une plage, une exception ou une derogation, la decision
du planning s'applique ; sans regle, le commutateur camera conserve son
comportement. Une camera explicitement desactivee reste toujours arretee.
La passerelle relit l'etat periodiquement sans navigateur. L'API livre aussi
un manifeste versionne et signe pour la camera ; le heartbeat accuse la
version et l'etat applique. Le serveur refuse une version devenue obsolete.

Sur la webcam PC autonome, le manifeste est verifie puis conserve sous DPAPI.
Lors d'une coupure reseau, une copie deja recue est evaluee localement au
demarrage et pendant l'analyse ; les detections produites restent dans la
file chiffree jusqu'au retour du serveur. La reconnexion recharge la version
courante et applique une desactivation. Un refus explicite HTTP 401/403 sur
l'appairage, l'etat, la presence ou une detection efface le planning local
et arrete la webcam sans relance automatique. Un redemarrage sans serveur
ne peut donc plus reutiliser cette copie ; verifier les droits et renouveler
l'appairage avant de reprendre. Les evenements en attente sont conserves.
Une revocation sur le
serveur ne peut toutefois pas etre connue tant que le PC reste sans Internet.

Recette réelle webcam du 14 octobre 2026 réussie sur le PC : manifeste
authentifié, DPAPI, arrêt du backend 8002, démarrage hors ligne puis activation
et arrêt selon une plage en heure réelle (42 images YOLO), nouvelle version
accusée à la reconnexion, révocation et refus de redémarrage hors ligne.

La passerelle RTSP accuse la version en ligne, mais ne reprend pas encore
l'acquisition RTSP hors Internet : sa source authentifiee n'est pas mise en
cache. La recette RTSP physique reste à faire. La migration
`homes.0017_camera_schedule_version_ack` doit etre
appliquee avant d'utiliser ce protocole en production. Le sous-lot webcam
reste a valider ; la recette RTSP et le deploiement restent ouverts.

## Recette webcam locale sans modification de la production

La base de developpement du depot a deja recu `homes.0017`. Utiliser un
nouveau terminal PowerShell depuis la racine pour le serveur de recette :

```powershell
$env:SENTINELLE_ENV_FILE = ''
$env:DJANGO_DEBUG = '1'
$env:DATABASE_URL = 'sqlite:///' + (Join-Path (Get-Location).Path 'db.sqlite3').Replace('\', '/')
$env:FCM_ENABLED = '0'
$env:REDIS_URL = ''
$env:EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8002 --noreload
```

Ces variables restent limitees a ce terminal. Aucun worker push de recette
n'est lance. Ouvrir `http://127.0.0.1:8002`, se connecter au compte de
developpement, puis creer une maison et une webcam **de recette**. Generer
son code d'appairage. Dans un second terminal depuis la racine :

```powershell
$recipeCredentials = Join-Path $env:LOCALAPPDATA 'SentinelleMaison\recette-sch002.credentials'
.\.venv\Scripts\python.exe -m gateway pair --server http://127.0.0.1:8002 --credentials-file "$recipeCredentials"
```

Revenir dans la fiche de la camera locale pour activer sa surveillance,
sans ligne de franchissement. Dans le planning de la maison de recette,
choisir une plage quotidienne qui commence dans deux minutes et finit deux
minutes plus tard (fuseau Africa/Kinshasa). Dans le second terminal :

```powershell
.\.venv\Scripts\python.exe -m gateway webcam --allow-development-model --credentials-file "$recipeCredentials"
```

Le fichier DPAPI distinct preserve l'appairage existant. Toujours utiliser
`--credentials-file` pour ces deux commandes de recette. Le code est saisi
dans le terminal sans affichage. Fermer les autres usages de la webcam.

1. Attendre le premier message de surveillance venant du serveur, puis
   arreter **uniquement le terminal du serveur 8002** avec Ctrl+C.
2. Observer `planning local hors ligne`, puis l'activation et l'arret aux
   deux limites de la plage. Ne pas fermer la passerelle ; elle reessaie
   le serveur toutes les dix secondes. La file locale doit rester disponible.
3. Relancer le serveur 8002 avec la meme commande. Observer le retour
   `serveur`, puis actualiser la fiche camera locale : **Dernier etat
   confirme** doit indiquer Arretee avec une heure recente. Cet etat est
   celui du dernier accuse, pas une mesure en direct pendant la coupure.
4. Revoquer l'appairage de cette seule camera de recette. Au prochain
   echange authentifie (au plus dix secondes hors requete en cours), la
   passerelle doit annoncer le refus et quitter. Arreter le serveur 8002,
   relancer la meme commande webcam : aucune analyse hors ligne ne doit
   reprendre avec ce planning retire. Arreter l'attente avec Ctrl+C.

La console de developpement affiche le code MFA si necessaire ; ne pas le
copier dans Trello. Cette recette ne teste pas les notifications telephone,
le redemarrage Windows automatique ni le flux RTSP physique. Elle a
été exécutée avec succès sur la webcam réelle le 14 octobre 2026, avec une
plage courte de 30 secondes et les caches de recette sur E:. La base de production sous AppData,
le port 8001 et son superviseur restent hors de ce parcours.

## Autorisations et audit

Les membres autorisés peuvent consulter le planning. Seul le propriétaire peut modifier le fuseau, créer, modifier ou supprimer une plage ou une exception, et poser une priorité manuelle. Chaque mutation est enregistrée dans le journal d’audit sans donnée secrète.

La priorité manuelle propose des durées bornées de 15 minutes à 24 heures. Après expiration, la décision revient automatiquement aux exceptions puis au planning.

## Limite de cet incrément

La coupure/reprise et la plage hors ligne ont été vérifiées sur la webcam
réelle le 14 octobre 2026, puis acceptées par l'utilisateur (« Validons les
pour passer »). Démarrage automatique Windows encore à vérifier ; cet accord
ne transforme pas le démarrage d'un processus en preuve de reboot.
La recette RTSP reste conditionnee a une camera H.264 reelle.
