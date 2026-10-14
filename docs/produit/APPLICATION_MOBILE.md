# Application mobile — web complet et pilote Android

## Version web adaptée au téléphone (28 septembre 2026)

Pour répondre à la demande de parité fonctionnelle, les pages Django existantes sont maintenant adaptées au mobile. Cette solution partage les fonctions et autorisations du site ; elle ne remplace pas silencieusement le pilote Flutter. Le choix de distribution définitif reste à valider avec l'utilisateur.

- Navigation inférieure : **Accueil / Maisons / Caméras / Alertes / Sécurité**.
- Maisons, plannings et exceptions, création et appairage des caméras, règles d'analyse, campagnes d'évaluation, événements et MFA restent accessibles sur leurs vraies pages.
- Titres de 24 px, sections de 18 px, texte courant de 14 à 16 px, contrôles tactiles de 44 px ; alertes neutres sans rouge sur téléphone, avec priorité toujours écrite.
- Manifeste PWA et commande d'installation lorsque le navigateur la propose. Hors ligne, seul un écran public est conservé ; aucune capture ni page privée n'est mise en cache par le service worker.
- L'installation exige un navigateur compatible et un contexte sécurisé (HTTPS ou localhost). Elle n'a pas encore été validée sur le téléphone réel. Le mode caméra reste soumis aux permissions et capacités du navigateur.

Aperçu local complet : `http://127.0.0.1:8001/tableau-de-bord/`. Sur Android relié par USB, conserver `adb reverse tcp:8001 tcp:8001`, puis ouvrir cette adresse dans le navigateur du téléphone. Aucun déploiement Render n'a été effectué.

Recette : se connecter avec MFA, parcourir les cinq onglets, ouvrir le planning d'une maison puis les règles et l'évaluation d'une caméra, consulter une alerte, vérifier les tailles et les couleurs. Tester ensuite la commande d'installation si disponible et le message hors ligne. Les décisions d'alerte sont définitives : utiliser une alerte de recette.

## Pilote Flutter

MOB-001 fournit un premier client Flutter installable sur Android. Il utilise exclusivement l’API utilisateur `/api/v1/` et conserve les jetons dans le stockage sécurisé du téléphone.

## Fonctionnalités du pilote

- connexion par identifiant et mot de passe, avec adresse du serveur intégrée à l’installation ;
- accès direct à **Créer un compte** et **Mot de passe oublié ?**, ouverts sur les parcours web réels du serveur configuré ;
- une session web déjà authentifiée est redirigée vers le tableau de bord au lieu de réafficher les pages publiques de connexion, d’inscription ou de récupération ;
- validation MFA avant la création de la session mobile ;
- lecture des nombres de maisons, caméras et événements visibles par l’utilisateur ;
- accueil synthétique avec état de protection, caméras actives et trois alertes récentes ;
- navigation **Accueil**, **Maisons**, **Caméras**, **Alertes** et **Sécurité**, détails caméra et alerte ;
- affichage des captures autorisées, activation de la surveillance selon les permissions et distinction entre l’état demandé et le dernier état confirmé par la passerelle ;
- historique paginé des alertes avec priorité, caméra, heure, confiance et regroupement ;
- aucun paramètre technique sur la page de connexion : le serveur est intégré à l’installation et le nom de l’appareil est généré automatiquement ;
- identifiant mémorisé dès la première tentative, même si le réseau ou le MFA échoue ; l’aperçu local utilise automatiquement `http://127.0.0.1:8001` ;
- rotation automatique du jeton de renouvellement, avec une seule rotation si plusieurs requêtes expirent ensemble ;
- restauration de la session au redémarrage de l’application ;
- révocation de la session côté serveur lors de la déconnexion ;
- effacement local des jetons même si le serveur est indisponible ;
- conservation chiffrée du dernier résumé sans aucune capture ; hors ligne, une bannière indique explicitement la date des données et propose de réessayer ;
- thèmes clair et sombre, zones tactiles d’au moins 44 px, zones sûres et libellés accessibles ;
- confirmation explicite avant la déconnexion.
- inscription push FCM après authentification et consentement système, rotation automatique du jeton et dissociation avant la déconnexion ; la fonction reste inactive lorsque Firebase n’est pas configuré au build.
- actualisation des alertes à la réception d’un push, au retour au premier plan et toutes les 15 secondes lorsque l’application est ouverte.

Le projet iOS est préparé dans le même dossier Flutter. Sa compilation et sa signature demanderont macOS et Xcode.

Flutter n'a pas encore la parité avec le web : gestion des maisons, plannings, règles d'analyse, campagnes et sécurité avancée restent dans l'interface web complète. Le direct distant et l'audio ne sont pas fournis. Le canal push est configuré et sa recette sur téléphone réel reste en cours. Le serveur d’aperçu Flutter sur `8081` est actuellement arrêté ; reconstruire le web avant de le relancer.

L’aperçu `8081` nécessite Django actif sur `127.0.0.1:8001`. L’origine locale est autorisée uniquement pour `/api/v1/` ; une autre origine doit être déclarée explicitement avec `MOBILE_WEB_ALLOWED_ORIGINS`.

Validation au 5 octobre : analyse Flutter sans erreur, **11 tests applicatifs ciblés réussis** après le correctif d’actualisation, et APK Firebase installé sur le téléphone réel. La récupération du mot de passe envoie un lien temporaire, conserve une réponse identique pour une adresse inconnue et limite les demandes répétées. Les tests couvrent aussi la redirection des utilisateurs déjà connectés et le refus du tableau de bord aux visiteurs anonymes.

## APK de recette

Le fichier à générer après toute modification est :

`mobile/build/app/outputs/flutter-apk/app-debug.apk`

Build Firebase de recette du 5 octobre 2026 : **168,6 Mo**, SHA-256 `7c0f144062841713a2834e81df1814cddc0b52fe070e50da4ef6c9fefd3c79f2`. Recalculer ces deux valeurs après toute reconstruction.

Build HTTPS Firebase du 9 octobre 2026, installé en mise à jour sur le V20 : **168,7 Mo**, SHA-256 `17f512b0dcb9ff998078dac7b40d24d26b81a330fa66af85f59a93e205875bf4`. L'ancienne adresse USB stockée est ignorée et sa session effacée ; l'identifiant et le nom du téléphone sont conservés.

Cet APK est une version de débogage destinée à la recette. Il utilise `https://sentinelle.smartxcongo.com` sans champ de configuration du serveur. Une version distribuée devra être signée ; le manifeste principal n'autorise pas le trafic HTTP en clair.

## Recette sur un téléphone Android

Le câble USB sert uniquement à installer l'APK de recette. La connexion utilise ensuite HTTPS et fonctionne aussi sans câble ou sur un autre réseau.

1. Activer les options développeur et le débogage USB sur le téléphone, le brancher au PC et accepter l’autorisation affichée.
2. Vérifier que le téléphone apparaît :

   ```powershell
   adb devices -l
   ```

3. Vérifier `https://sentinelle.smartxcongo.com/health/` depuis le navigateur du téléphone.
4. Installer l'APK en mise à jour, sans désinstaller l'application :

   ```powershell
   adb install -r E:\CodexCaches\sentinelle-build-20261007-145340\build\app\outputs\flutter-apk\app-debug.apk
   ```

5. La première ouverture invalide l'ancienne session USB et affiche la connexion normale. Aucun champ Serveur n'est à remplir.
6. Vérifier **Créer un compte** et **Mot de passe oublié ?**, puis saisir le compte web, le mot de passe et le code MFA reçu.
7. Dans **Accueil**, vérifier l’état de protection, le nombre de caméras actives et les trois alertes récentes.
8. Dans **Alertes**, charger une page supplémentaire et vérifier l’ordre, la priorité, la caméra, la date et la confiance.
9. Fermer complètement l’application puis la rouvrir : la session doit être restaurée sans redemander le mot de passe.
10. Couper temporairement Wi-Fi et données mobiles, puis tirer l'écran vers le bas : la bannière hors ligne doit afficher la date des données conservées, sans image mise en cache. Rétablir ensuite Internet.
11. Dans **Sécurité**, toucher **Se déconnecter**, annuler une première fois, puis confirmer. Au prochain lancement, l’écran de connexion doit réapparaître.

Débrancher le câble ne doit pas interrompre la connexion tant que le téléphone et le PC ont accès à Internet et que la tâche locale de production tourne.

## Développement

Depuis `mobile/` :

```powershell
flutter pub get
flutter analyze
flutter test
flutter build apk --debug
```

L'adresse HTTPS de production est intégrée par défaut. Pour un serveur de développement distinct, la remplacer explicitement à la compilation :

```powershell
flutter build apk --dart-define=SENTINELLE_API_BASE_URL=https://serveur-de-test.exemple.fr
```

Sur le poste Windows actuel, le script contourne le répertoire temporaire Cygwin incompatible avec les sockets AF_UNIX de Java en définissant un dossier dédié via `jdk.net.unixdomain.tmpdir`. Il contrôle aussi l'adresse du serveur, l'espace disque, la présence des dépendances et la configuration Firebase avant de lancer Flutter. Il place automatiquement le cache Gradle sur `E:` lorsque ce lecteur existe. Pour préserver `C:`, `mobile/build` est actuellement une jonction locale vers `E:\CodexCaches\sentinelle-mobile-build`.

```powershell
Set-Location 'C:\Users\Dell Latitude 5400\OneDrive\Documents\ChatGPT\projet_maison_intelligente\mobile'
.\tool\build_android.ps1 -WithoutFirebase -CheckOnly
.\tool\build_android.ps1 -WithoutFirebase
```

`-WithoutFirebase` produit un APK de contrôle sans notifications push. Pour la recette de `PUSH-001`, définir les quatre variables publiques indiquées dans `NOTIFICATIONS_PUSH.md`, retirer cette option et lancer `.\tool\build_android.ps1`. Le script affiche ensuite le chemin, la taille et l'empreinte SHA-256 de l'APK sans afficher les valeurs Firebase.
