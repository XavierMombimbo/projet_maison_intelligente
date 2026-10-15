# Sentinelle Maison mobile

Client Flutter de l’API utilisateur Sentinelle Maison, avec Android comme première cible.

Le pilote couvre la connexion par mot de passe et MFA, le stockage sécurisé des jetons, leur renouvellement rotatif, la restauration de session, le tableau de bord filtré et la révocation lors de la déconnexion.

Consultez [`docs/produit/APPLICATION_MOBILE.md`](../docs/produit/APPLICATION_MOBILE.md) pour la compilation, l’APK et le parcours de recette sur téléphone réel.

## Vérifications

```powershell
flutter pub get
flutter analyze
flutter test
.\tool\build_android.ps1 -WithoutFirebase
```

Le script configure automatiquement le cache Gradle et le répertoire de sockets Java nécessaires sur ce poste. `-WithoutFirebase` construit l’APK de contrôle sans notifications push ; retirer cette option après avoir défini la configuration Firebase décrite dans la documentation.
