# Notifications push

## Message combiné — 22 octobre 2026

Une preuve serveur de suspicion d’arme associée à une personne utilise le texte
« Personne détectée avec port d’arme probable » dans les alertes web, la fiche et
le corps FCM. Le champ de transport `person_weapon_suspicion=true` permet au
nouveau client Android de reprendre ce texte au premier plan, sans accepter du
texte arbitraire à afficher. L’application déjà installée doit être mise à jour
pour ce nouveau rendu au premier plan. Une arme seule garde le libellé général.

Les préférences de catégories, regroupement, horaires silencieux et visibilité
Android private/public/secret continuent à s’appliquer. Aucun nom de personne,
visage, score biométrique ou image n’est ajouté au push. L’envoi à Firebase ne
prouve ni réception ni affichage sur un téléphone. Le mode combiné académique
est activé séparément ; l’ancien essai isolé reste sans boîte d’envoi ni push.

PUSH-001 utilise Firebase Cloud Messaging pour Android et pourra relayer APNs pour iOS. Le fournisseur constitue un transport : son acceptation n’est jamais considérée comme une preuve de réception sur le téléphone.

## Cycle de vie

1. Après la connexion MFA, Flutter demande la permission système puis croise la réponse Firebase avec `NotificationManager.areNotificationsEnabled()` sur Android. Un blocage dans les réglages de l’application est ainsi enregistré comme `denied`, même si Firebase retourne encore `authorized`.
2. Le jeton FCM est envoyé à `PUT /api/v1/push/installation/` puis resynchronisé sur `onTokenRefresh`.
3. Le serveur chiffre le jeton par AES-GCM, conserve une empreinte HMAC et le rattache à une seule `MobileSession`.
4. Une alerte non regroupée crée au plus une `PushDelivery` par installation encore active et encore autorisée à voir l’événement.
5. `dispatch_push_deliveries` revérifie les droits, tente l’envoi et enregistre attente, reprise, acceptation fournisseur, réception applicative, invalidité ou échec définitif.
6. Une permission `denied`, la déconnexion ou toute révocation de session efface le jeton chiffré et rend les livraisons restantes annulables.
7. L’application recharge l’historique après un push reçu, au retour au premier plan et toutes les 15 secondes lorsqu’elle reste ouverte. Cette actualisation de l’interface ne remplace pas la notification système.

Le message contient uniquement `event_id`, `delivery_id`, un type technique, le choix `lock_screen` et le texte générique « Une nouvelle alerte est disponible. ». Il ne contient ni capture, ni nom de personne, ni secret, ni donnée biométrique. L’ouverture recharge l’événement depuis l’API et ses droits courants.

## Configuration serveur

Définir hors Git :

- `PUSH_TOKEN_ENCRYPTION_KEY` : clé AES-GCM URL-safe base64 de 32 octets ;
- `PUSH_TOKEN_PEPPER` : secret indépendant d’au moins 32 octets ;
- `FCM_ENABLED=True` ;
- `FCM_PROJECT_ID` ;
- `FCM_SERVICE_ACCOUNT_JSON` : JSON complet du compte de service sur une ligne, ou utiliser les identifiants applicatifs Google par défaut ;
- `PUSH_MAX_ATTEMPTS=5` et `PUSH_RETRY_BASE_SECONDS=30` par défaut.

Le compte de service doit avoir le droit d’envoyer via l’API FCM du projet cible. Le processus de livraison exécute périodiquement :

```powershell
.\.venv\Scripts\python.exe manage.py dispatch_push_deliveries --limit 100
```

En développement local, lancer un seul processus continu dans un terminal dédié :

```powershell
.\.venv\Scripts\python.exe -u manage.py dispatch_push_deliveries --watch --interval 5
```

Le processus vérifie les livraisons éligibles toutes les cinq secondes après chaque lot, respecte les échéances de reprise et s'arrête avec Ctrl+C. Il renouvelle les connexions de base et réessaie après une indisponibilité temporaire, sans afficher les détails de connexion. Les erreurs inattendues restent visibles. Sans `--watch`, la commande traite un seul lot comme auparavant. `--limit` borne chaque lot entre 1 et 10000 et `--interval` accepte de 1 à 3600 secondes.

Sans processus actif, la livraison reste `pending` même si l’événement est déjà visible par l’API. Le démarrage automatique au redémarrage de la machine et la supervision relèvent du déploiement d’exploitation ; `--watch` seul ne les installe pas.

Les délais de reprise sont bornés et croissent par facteur quatre. Un jeton déclaré non enregistré ou invalide par FCM est immédiatement retiré.

## Configuration Flutter

Les valeurs publiques Firebase sont injectées au build ; aucun fichier de compte de service ne va dans l’application. Dans un PowerShell Windows normal, les placer dans l'environnement puis utiliser le script de construction :

```powershell
$env:FIREBASE_API_KEY = '...'
$env:FIREBASE_APP_ID = '...'
$env:FIREBASE_MESSAGING_SENDER_ID = '...'
$env:FIREBASE_PROJECT_ID = '...'
Set-Location 'C:\Users\Dell Latitude 5400\OneDrive\Documents\ChatGPT\projet_maison_intelligente\mobile'
.\tool\build_android.ps1 -CheckOnly
.\tool\build_android.ps1
```

Le contrôle refuse une configuration Firebase partielle et n'affiche jamais les valeurs. Pour le web, ajouter aussi `FIREBASE_WEB_VAPID_KEY` et les paramètres web nécessaires. Sans les quatre paramètres Firebase principaux, le module reste inactif et ne demande aucune permission.

## Préférences personnelles par caméra (PUSH-002, étape 1)

Depuis la fiche caméra web, « Mes notifications » ouvre les préférences du compte connecté pour tous ses appareils. Sans préférence enregistrée, le comportement antérieur est conservé. Les cases permettent de couper cette caméra, les événements de personne ou les événements d'objets (y compris animaux). Les droits caméra sont vérifiés à chaque lecture et écriture ; chaque utilisateur règle uniquement sa propre réception.

Le filtre s'applique avant création de la livraison et à nouveau avant envoi. Une livraison en attente devenue indésirable passe à `cancelled` ; une notification déjà acceptée par FCM ne peut pas être retirée. Réactiver ne réexpédie pas les livraisons annulées. L'historique, la surveillance et les notifications des autres comptes restent inchangés. Une catégorie désactivée n'a pas d'exception urgente.

Migration : `notifications.0002_camerapushpreference`. Redémarrer serveur et worker après application ; aucun changement d'APK pour ces préférences web.

### Plages silencieuses (étape 2)

Deux heures facultatives définissent une plage quotidienne dans le fuseau IANA de la maison. Elles doivent être toutes les deux remplies ou vides, et différentes. Début inclus, fin exclue ; le passage de minuit et les changements d'heure suivent le fuseau de la maison. Les événements sont conservés, mais les notifications filtrées ne sont pas différées.

L'option `urgent_during_quiet`, désactivée par défaut, laisse passer uniquement la priorité serveur `URGENTE` (100). Elle ne réactive jamais une caméra ou catégorie coupée et ne contourne aucun réglage Android. Une livraison en attente entrant dans la plage est annulée avant appel FCM. Migration `notifications.0003_camerapushpreference_quiet_end_and_more`.

Recette : régler une plage contenant l'heure courante, produire une alerte non urgente, vérifier l'historique sans push. Tester une alerte réellement classée urgente avec l'option désactivée puis activée. Effacer les deux heures pour revenir au fonctionnement normal. Redémarrer serveur et worker ; aucun nouvel APK requis.

## Recette téléphone

### Confidentialité et ouverture ciblée (PUSH-002)

`lock_screen` est personnel et par caméra, disponible sur le web et dans « Mes notifications » mobile. Trois valeurs Android : `private` (masquer le contenu, défaut), `secret` (masquer la notification verrouillée), `public` (message générique visible). Le texte reste toujours « Une nouvelle alerte est disponible. », sans image, nom de caméra ni détail de détection. Les réglages système/canal Android restent prioritaires ; ce choix ne pilote pas l'écran verrouillé iOS. Il concerne les nouveaux envois, pas les notifications déjà affichées. Un ancien client omettant ce champ conserve le choix enregistré. Migration `notifications.0004_camerapushpreference_lock_screen`.

Le toucher FCM (arrière-plan/démarrage) et natif (notification créée au premier plan) transmet uniquement des identifiants. Le client valide l'UUID, attend la connexion si nécessaire, puis charge `GET /api/v1/events/{uuid}/` avec la session courante. Le serveur revérifie les droits caméra. Aucun détail du cache n'est utilisé en cas de refus ; une panne propose Réessayer. La réception seule actualise l'historique sans changer de page. Chaque notification locale possède un PendingIntent distinct ; la déconnexion masque et ferme la fiche ouverte.

Recette : installer le nouvel APK Firebase, appliquer la migration et redémarrer Django ainsi que le worker. Produire de nouvelles alertes pour chacun des trois choix de confidentialité. Toucher deux alertes distinctes depuis le volet de notifications, puis tester arrière-plan et application terminée (pas arrêt forcé). Tester ouverture avant connexion et retrait des droits avant de toucher une ancienne notification. Les tests automatisés ne remplacent pas cette recette sur V20.

Le canal Android `sentinelle_alerts` est créé à l'ouverture de l'application avec importance haute, son et vibration. Au premier plan, le callback FCM affiche une notification native puis accuse la réception applicative ; en arrière-plan, Firebase affiche la notification sur ce même canal. Le toucher ouvre la fiche autorisée de l'alerte. Le texte reste générique. Les réglages utilisateur du canal, le mode silencieux et les restrictions Android restent prioritaires. L'accusé applicatif ne prouve pas que l'utilisateur a vu le bandeau.

Après ce changement natif, reconstruire et réinstaller l'APK avec Firebase, ouvrir l'application une fois et redémarrer le worker serveur. Vérifier le bandeau et le son avec une nouvelle alerte au premier plan puis en arrière-plan. Le polling du worker ajoute jusqu'à son intervalle au délai avant tentative FCM ; aucun délai de réception strict n'est garanti.

Sur un téléphone réel, produire une alerte pour chacun des états suivants : application au premier plan, en arrière-plan, terminée, arrêt forcé, permission refusée et économie d’énergie. Pour chaque essai, relever la ligne `PushDelivery`, l’acceptation FCM éventuelle, la réception accusée par l’application et la présence de l’événement dans l’historique. Après un arrêt forcé Android, rouvrir l’application avant de conclure à une reprise normale des messages.

Une simulation, un test unitaire ou une acceptation FCM seule ne valide pas PUSH-001.
