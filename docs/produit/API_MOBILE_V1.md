# API mobile utilisateur v1

Base : `/api/v1/`. Toutes les réponses d’authentification utilisent `Cache-Control: no-store`.

## Connexion

Un nouveau compte peut d'abord activer sa protection sur `/securite/mfa/`
par un code e-mail, sans application supplémentaire. L'envoi est explicite,
limité et n'active rien à lui seul ; la confirmation d'un code récent reçu
par cette session active la protection et affiche les codes de récupération
une seule fois. Le secret d'un éventuel QR abandonné est renouvelé à cette
activation. Le parcours QR reste facultatif. Les comptes déjà protégés
conservent leurs facteurs. Cette évolution ne change pas le contrat API.

1. `POST /auth/login/` reçoit `identifier`, `password`, `device_id` et `device_name`. Un mot de passe correct produit seulement un défi temporaire et envoie un code MFA par e-mail.
2. `POST /auth/mfa/verify/` reçoit `challenge` et `code`. Un code e-mail, TOTP ou de récupération valide produit un jeton d’accès de courte durée et un jeton de renouvellement opaque.
3. `POST /auth/refresh/` reçoit `refresh_token`. Chaque utilisation remplace immédiatement ce jeton ; sa réutilisation est refusée.

Les jetons d’accès ont l’émetteur `sentinelle-maison` et l’audience `sentinelle-mobile-api`. Un jeton caméra ne peut donc pas être accepté par cette API.

## Sessions par appareil

- `GET /auth/sessions/` liste les appareils et identifie la session courante.
- `POST /auth/sessions/{uuid}/revoke/` révoque uniquement la session choisie.
- `GET /me/` retourne le compte associé au jeton.

Les secrets de renouvellement et de défi ne sont jamais stockés en clair : seuls leurs HMAC SHA-256 sont conservés.

## Installation push

- `GET /push/installation/` retourne l’état de l’installation courante sans jamais exposer son jeton.
- `PUT /push/installation/` reçoit `platform`, `permission` et, lorsque la permission est accordée, `token`. Une rotation rattache le jeton uniquement à la dernière session qui l’a présenté.
- `DELETE /push/installation/` dissocie l’installation. La révocation d’une session produit le même effet côté serveur.
- `POST /push/deliveries/{uuid}/received/` accuse la réception par l’application authentifiée. Une acceptation FCM reste enregistrée séparément et ne prouve pas la réception sur le téléphone.

Les jetons FCM sont chiffrés par AES-GCM avec une clé dédiée et recherchés par empreinte HMAC. Ils ne sont renvoyés ni par l’API ni par l’administration.

## Ressources

- `GET /houses/` et `/houses/{id}/`
- `GET /cameras/` et `/cameras/{uuid}/`
- `GET /events/` et `/events/{uuid}/`

Les listes sont paginées. Elles utilisent directement `Maison.objects.visible_to`, `Camera.objects.visible_to` et `Evenement.objects.visible_to`, les mêmes filtres que le site web.

L’API accepte les appels web uniquement depuis les origines déclarées dans `MOBILE_WEB_ALLOWED_ORIGINS`. En développement, `http://127.0.0.1:8081` et `http://localhost:8081` sont ajoutées automatiquement. Les en-têtes CORS ne sont appliqués qu’à `/api/v1/` et aucune origine arbitraire n’est reflétée.

## Consultation et actions mobiles

- Les événements sont triés par réception décroissante ; `GET /events/?camera={uuid}&page=2&page_size=20` filtre et pagine l’historique d’une caméra visible.
- Les caméras exposent `can_control`, `latest_capture_event_id`, `surveillance_active` (état demandé), `surveillance_appliquee` et `surveillance_appliquee_le` (dernier état confirmé par la passerelle). Les événements exposent `has_capture` et `can_control`.
- `GET /events/{uuid}/capture/` déchiffre la capture après contrôle de visibilité. Réponse image privée, `no-store`, sans URL publique ni jeton dans l’URL.
- `POST /cameras/{uuid}/monitoring/` reçoit `{"active": true}` ou `false`. Réservé au propriétaire ; une caméra révoquée est refusée. L’action est auditée.
- `POST /api/cameras/heartbeat/` accepte facultativement `{"monitoring_active": true}` ou `false` pour accuser l’état réellement appliqué par la passerelle. Sans ce champ, le heartbeat met uniquement à jour la dernière connexion.
- `POST /events/{uuid}/decision/` reçoit `{"decision": "confirmed"}` ou `"false_alarm"`. Mêmes droits de contrôle que sur le web, audit et notification de mise à jour. Une alerte déjà traitée renvoie 409 ; une valeur invalide renvoie 400.
- Aucun flux audio/vidéo en direct n’est ajouté. Les aperçus affichent les captures réelles disponibles ; aucune photo de démonstration n’est présentée comme une caméra du compte.

## Diagnostic manuel

Après connexion au site, ouvrir `/securite/api-mobile/test/`. Aucun jeton n’est enregistré dans le navigateur ; ils restent seulement en mémoire jusqu’au rechargement de la page.

## Gestion des maisons depuis Flutter

### Gestion des cameras

#### Appairage depuis le mobile

`POST /api/v1/cameras/{id}/pairing-code/` (corps vide) reserve au proprietaire.
Reponse 201 : `code` (chaine de six chiffres) et `expires_at` (ISO 8601).
Code valable cinq minutes, stocke hache, usage unique ; un nouveau code invalide
le precedent. Service et limite `pairing_code` identiques au web. Non-proprietaire
404, camera appairee/revoquee 409, limite 429 avec `Retry-After`. Reponse privee
`no-store` ; audit sans code ni identifiant de passerelle.

Flutter : `screens/camera_pairing_screen.dart`, generation explicite, expiration,
suivi du statut par GET detail toutes les cinq secondes au premier plan.
Code conserve uniquement dans l'etat de l'ecran, efface en arriere-plan et a la
fermeture ; pas de copie automatique. Le telephone de gestion ne consomme pas
le code et ne conserve aucun secret de passerelle. Saisir le code sur le poste
camera via le parcours web existant « Connecter une camera » ou la passerelle.
La capture et son autorisation restent sur ce poste. L'appairage ne vaut pas
demarrage ni validation d'un flux RTSP physique.

- `POST /api/v1/cameras/` : `maison`, `nom`, `type_source` (`webcam` ou `rtsp`).
  RTSP : `adresse_rtsp`, `utilisateur_rtsp`, `mot_de_passe_rtsp`.
  Reutilise `CameraForm` du web : maison proprietaire uniquement, validation RTSP,
  identifiants chiffres au repos et jamais retournes. Reponse 201 sans secrets.
  La camera est creee non appairee et surveillance inactive.
- `POST /api/v1/cameras/{id}/` : `nom` uniquement ; aucun changement de maison,
  source, secrets ou appairage. Proprietaire uniquement, camera revoquee 409,
  membre avec acces 403, sans acces 404. Reponse 200 sans secrets.
- Flutter : ecran dedie `screens/camera_form_screen.dart`, ajout depuis Cameras,
  renommage depuis la fiche ; erreurs conservant la saisie et double envoi bloque.
  Appairage et reglages avances ne sont pas couverts par cette etape.

- `POST /api/v1/houses/` : `nom` (1 à 120 caractères après trim), `fuseau_horaire` IANA (défaut Africa/Kinshasa). Propriétaire imposé par la session authentifiée. Retour 201 avec le même objet que la lecture.
- `POST /api/v1/houses/{id}/` : modification partielle du nom/fuseau, propriétaire uniquement. Membre accepté : 403 ; maison invisible : 404. Identifiant, rôle, date et propriétaire ne sont pas modifiables. Retour 200.
- Création et modification auditées. Les routes de lecture restent compatibles. Aucune migration.

## Lot gestion mobile

Routes sous `/api/v1/`, authentification mobile obligatoire. Implementation dans
`homes/mobile_management.py`, ecrans Flutter separes sous `mobile/lib/screens/`.

- `GET/POST houses/{id}/schedule/` : lecture maison visible ; ecriture proprietaire.
  GET retourne fuseau, decision actuelle, horaires quotidiens, plages, exceptions
  et priorite temporaire. POST utilise `action` : `daily` (heure_activation,
  heure_arret), `daily_clear`, `window` (id facultatif, nom, jour 0-6, heure_debut,
  heure_fin, active), `window_delete` (id), `exception` (id facultatif, nom,
  date_debut/date_fin locales YYYY-MM-DDTHH:MM dans le fuseau maison,
  surveillance_active, priorite 0-100), `exception_delete` (id), `override`
  (surveillance_active, duree_minutes parmi 15/30/60/120/480/1440), `override_clear`.
  Les formulaires et l'arbitrage du web sont reutilises. Mutations transactionnelles,
  collisions de plages retournees en 400 sans perte du planning existant.
- `GET/POST cameras/{uuid}/preferences/` : camera visible uniquement, preferences
  du compte courant imposees. Champs enabled, people, objects_enabled,
  quiet_start/quiet_end facultatifs ensemble, urgent_during_quiet et lock_screen
  (`private` par defaut, `secret` ou `public`, ecran verrouille Android). Un POST
  ancien sans lock_screen conserve la preference existante. GET ne cree
  pas d'enregistrement. POST exige les quatre booleens, valide via le formulaire web.
  Effacer les deux heures avec null. Aucun changement de surveillance ni rattrapage.
- `GET/POST houses/{id}/members/` : proprietaire seulement. GET renvoie membres
  (username, role, status, is_owner, access) et cameras de la maison. POST `invite`
  exige username d'un compte existant et role family/guest ; cree toujours une
  invitation pending. Aucun e-mail n'est envoye : elle figure dans Invitations.
  POST `update` exige id/role ; `remove` exige id. Le proprietaire est immuable.
  `access` est la liste complete des droits a conserver : camera_id, peut_voir,
  peut_controler. Le controle exige la lecture ; seules les cameras de cette
  maison sont acceptables. Retrait et remplacement des droits sont transactionnels.
- `GET/POST invitations/` : invitations en attente du compte courant. POST id et
  action accept/refuse ; impossible d'accepter pour autrui ou de rejouer une reponse.
  Les droits restent inactifs avant acceptation. Retrait du membre coupe l'acces.

Navigation : Maisons > menu > Horaires/Membres ; Maisons > Invitations ;
fiche camera > Mes notifications. Aucune migration. Les controles proprietaire,
camera visible et membership accepte existants restent la source des autorisations.
Ce lot n'ajoute pas l'execution autonome RTSP (SCH-002/CAM-002), la confidentialite
push configurable ni le lien profond (reste de PUSH-002).
