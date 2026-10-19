# Profils biométriques volontaires

FACE-001 définit le consentement, les droits, le stockage et le retrait des profils. FACE-002 ajoute une recette académique non commerciale avec InsightFace 0.7.3 et les poids officiels ArcFace `buffalo_l`. Aucune photo brute n’est persistée.

## Reconnaissance dans Mode caméra

Une présence reconnue reste dans l'historique mais n'est pas diffusée comme
`alert.created` sur le canal WebSocket : ni sirène ni notification visuelle.
La suppression s'applique aussi aux reprises de boîte d'envoi ; le client web
ignore également les messages marqués `notification_suppressed=true`.
Le détail affiche « Présence reconnue · notification silencieuse », sans
présenter cette présence comme une intrusion à confirmer. Les inconnus et les
franchissements de ligne conservent leurs alertes.

Avec `BIOMETRIC_WEB_RECOGNITION_ENABLED=True` et le répertoire ArcFace configuré,
le navigateur conserve la détection personne/animal et envoie sa capture
d'événement habituelle. Le serveur vérifie la session, les droits caméra, le CSRF,
la signature et la capture avant de comparer le visage aux profils actifs et
enrôlés des membres acceptés de cette seule maison. Aucun gabarit, nom, identifiant
de profil ou score facial n'est renvoyé au navigateur. La capture de l'événement
conserve son stockage chiffré existant ; aucun portrait ou gabarit supplémentaire
n'est enregistré par la comparaison.

La comparaison précède la décision d'alerte. Une présence reconnue est conservée
sans notification ; un franchissement de ligne reste urgent. Un visage non
exploitable, plusieurs personnes, aucun profil admissible ou un modèle occupé
produisent un état indisponible distinct d'une personne non reconnue. Cette
première portée exige une seule personne et un seul visage net dans la capture,
avec le visage situé dans la boîte de la personne détectée. Les droits et le
profil reconnu sont revérifiés après l'inférence ; un retrait ou changement de
version empêche de rendre la présence silencieuse.

L'écran affiche **Dernière vérification faciale**, horodatée, pour la dernière
capture envoyée : ce n'est pas une identification continue de chaque cadre vidéo.
La vérification se renouvelle à l'événement suivant, avec le délai de 15 secondes
déjà appliqué par Mode caméra. Le contrat signé entrant reste v2 ; le résultat
calculé par le serveur est enregistré séparément dans `face_verification`
(`source=server`), puis repris dans les statuts d'événement existants. Le serveur
refuse tout statut facial fourni par un jeton navigateur. Une retransmission
identique retrouve le résultat initial sans relancer la comparaison.

Recette : libérer la webcam de la passerelle autonome, ouvrir Mode caméra avec
le compte autorisé, puis démarrer l'aperçu et rester seul de face dans la zone.
Vérifier « Profil reconnu · présence silencieuse » et l'historique sans nouvelle
notification. Arrêter immédiatement doit fermer la webcam et empêcher un résultat
tardif de réapparaître. L'enrôlement déjà accepté ne doit pas être refait.

## Consentement et droits

- Seul un membre accepté peut créer son propre profil dans une maison.
- Un seul profil actif est autorisé par personne et par maison.
- Le propriétaire voit les métadonnées des profils de la maison et peut les retirer, mais ne peut pas exporter le gabarit d’une autre personne.
- La personne concernée peut exporter ses propres données et retirer son profil à tout moment.
- La création, l’export, le retrait, la synchronisation et les confirmations de purge sont audités sans gabarit ni donnée faciale.

L’écran se trouve dans **Maison → Profils volontaires**. La création enregistre le consentement `face-profile-v1`. Lorsque le service web est activé, elle mène directement à **Enregistrer mon visage**. Un profil en attente peut reprendre cette étape depuis la même page, sans export d’identifiant ni commande technique. Le parcours local en console reste disponible pour la recette de passerelle.

## Enrôlement depuis la plateforme

1. Le membre accepté crée son propre profil et donne son accord.
2. Il confirme l’envoi d’une capture puis clique sur **Ouvrir ma caméra**. Aucune caméra ni aucun microphone ne s’active automatiquement.
3. Il se place seul, de face et bien éclairé, puis clique sur **Enregistrer mon visage**. La caméra est fermée immédiatement après la capture ; un message confirme le résultat.

Une seule image JPEG est envoyée en HTTPS au serveur de la plateforme, puis traitée en mémoire. Le serveur utilise les poids ArcFace officiels déjà approuvés dans le cadre académique non commercial ; il conserve uniquement le gabarit normalisé de 2 048 octets, chiffré comme les profils locaux. Aucun service externe ne reçoit l’image. Les modèles d’âge et de genre ne sont pas utilisés dans ce parcours.

La capture est limitée à 384 Kio et le corps JSON à 530 Kio. Une protection ASGI dédiée rejette les corps excessifs avant la mise en tampon de Django, y compris sans en-tête Content-Length. Les images non JPEG, dimensions excessives, visages absents ou multiples sont refusés. Le serveur ne conserve pas de photo ; le navigateur ne crée ni fichier ni stockage local de capture.

Seule la personne concernée peut enrôler son profil actif ; le propriétaire ne peut pas le faire à sa place. Les droits et l’état du consentement sont revérifiés après l’inférence, avant écriture sous verrou. Une capture ne remplace pas silencieusement un profil déjà enrôlé. Les requêtes sont protégées par session, MFA existante, CSRF, cinq essais par cinq minutes et réponses `no-store`. L’audit contient seulement le format et l’origine web, jamais l’image ou le vecteur.

Configuration serveur : `BIOMETRIC_WEB_ENROLLMENT_ENABLED=True` et `BIOMETRIC_FACE_MODEL_ROOT` vers le répertoire externe approuvé contenant `models/buffalo_l`. Le contrôle du registre et des empreintes précède le chargement du modèle ; un seul traitement est admis à la fois par processus. Le modèle reste en mémoire pour les demandes suivantes. Aucun téléchargement de poids n’est effectué par ce parcours.

L’interface affiche une seule action principale à chaque étape. La gestion, l’export et le retrait sont accessibles dans **Gérer les profils et mes données** ; les détails d’usage se trouvent dans **À savoir sur mon profil**. Une reconnaissance n’est pas une preuve de présence réelle et ne commande jamais un accès ni le désarmement de la surveillance.

## Recette académique ArcFace (FACE-002)

Les poids publics InsightFace sont réservés à la recherche non commerciale. Cette recette ne peut donc être utilisée que dans le cadre académique confirmé pour ce projet ; elle ne constitue pas une autorisation de produit commercial. Les cinq fichiers `buffalo_l` sont conservés hors Git sur `E:\CodexCaches\sentinelle-face-20261014\models\buffalo_l`, et leur taille et SHA-256 sont contrôlés contre `config/model_registry.json` avant chaque opération.

Depuis une console de la passerelle, après création volontaire du profil, exécuter :

```powershell
python -m gateway face-enroll --profile-id <UUID-de-son-profil> --model-root E:\CodexCaches\sentinelle-face-20261014 --academic-use-acknowledged
python -m gateway face-check --model-root E:\CodexCaches\sentinelle-face-20261014 --academic-use-acknowledged
```

Chaque commande utilise une seule image en mémoire, demande un seul visage avec un score de détection d’au moins 0,65, produit un gabarit ArcFace normalisé de 2 048 octets, puis libère immédiatement la webcam. L’enrôlement envoie seulement le gabarit chiffré au serveur. La comparaison synchronise le cache DPAPI de la passerelle sur `E:` et ne sort que `reconnu`, `inconnu`, `indisponible`, ou une erreur de qualité. Elle ne déclenche ni ouverture, ni fermeture, ni commande d’accès.

### Mesure consentie FAR / FRR

Après le pilote, chaque participant volontaire effectue au moins dix comparaisons de son propre visage et dix comparaisons avec un visage volontaire différent ou aucun visage. Pour chaque condition `jour`, `faible lumière`, `distance`, `occultation` et `plusieurs visages`, consigner seulement les compteurs suivants dans le compte rendu : essais authentiques, reconnus, faux rejets, essais non correspondants, inconnus, fausses acceptations et erreurs de qualité. Calculer `FRR = faux rejets / essais authentiques exploitables` et `FAR = fausses acceptations / essais non correspondants exploitables`; exclure les erreurs de qualité des deux dénominateurs et les déclarer séparément. Aucun fichier image, UUID de profil, vecteur, score individuel ou nom de participant ne doit figurer dans ce compte rendu.

## Chiffrement serveur

Les gabarits sont chiffrés par AES-GCM avec `BIOMETRIC_ENCRYPTION_KEY`, une clé de 32 octets encodée en base64 URL-safe. L’identifiant UUID du profil est utilisé comme donnée associée. La taille maximale est contrôlée par `BIOMETRIC_TEMPLATE_MAX_BYTES`, soit 64 Kio par défaut.

Un retrait est irréversible : le texte chiffré, le nonce et le format sont effacés immédiatement, la version augmente et seul un tombstone technique subsiste pour ordonner la purge des passerelles.

## Synchronisation passerelle

- `GET /api/camera/me/profils-biometriques/` retourne uniquement les gabarits actifs de la maison de la caméra, les tombstones, une génération et `valid_until`.
- `POST /api/camera/me/profils-biometriques/purges/` confirme qu’une version retirée n’est plus dans le cache local.
- Les réponses sont privées et `no-store`; le jeton caméra reste limité à sa propre maison.
- La durée par défaut est `BIOMETRIC_CACHE_TTL_SECONDS=300`. Après expiration, `profiles_for_comparison()` lève `BiometricCacheExpired` et interdit toute comparaison jusqu’à une synchronisation réussie.

Sous Windows, `gateway.biometrics` est protégé par DPAPI et remplacé atomiquement. La passerelle écrit d’abord le cache sans les profils retirés, puis envoie l’accusé de purge. Une panne avant l’écriture ne produit donc pas de fausse confirmation.

## Recette FACE-001 et FACE-002

1. Ouvrir une maison puis **Profils volontaires**.
2. Vérifier que le profil ne peut pas être créé sans cocher le consentement.
3. Créer son profil et vérifier l’état **En attente d’enrôlement**.
4. Exporter ses données et vérifier qu’un autre membre ou le propriétaire ne peut pas exporter ce profil.
5. Retirer le profil et vérifier son état **Retiré**.
6. Hors du pilote 24 h, arrêter la capture webcam concurrente, enrôler volontairement un seul visage avec `face-enroll`, puis effectuer `face-check` avec le même visage et avec un visage absent ou différent. Noter les résultats sans conserver d’image ni d’identifiant dans le compte rendu.

Le chiffrement, l’isolation inter-maison, la destruction du gabarit, le tombstone, l’accusé caméra et l’expiration du cache sont couverts automatiquement. Le seuil initial est 0,45 en similarité cosinus : la mesure FAR/FRR reste à réaliser sur des volontaires consentants, dans les conditions jour/nuit, distance, occultation et multiples personnes documentées pour la recette académique.
