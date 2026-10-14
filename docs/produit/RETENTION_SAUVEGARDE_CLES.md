# Rétention, sauvegarde et clés

## Durées par défaut

| Donnée | Durée | Variable |
|---|---:|---|
| Captures chiffrées | 30 jours | `CAPTURE_RETENTION_DAYS` |
| Événements | 90 jours | `EVENT_RETENTION_DAYS` |
| Nonces de requête caméra | 24 heures | `CAMERA_NONCE_RETENTION_HOURS` |
| Outbox déjà livrée | 7 jours | `OUTBOX_RETENTION_DAYS` |
| Journal d’audit | 365 jours | `AUDIT_RETENTION_DAYS` |

Une alerte encore en attente dans l’outbox protège son événement et sa capture contre la purge. Prévisualiser puis exécuter :

```powershell
python manage.py purge_expired_data --dry-run
python manage.py purge_expired_data
```

## Sauvegarde chiffrée

`BACKUP_ENCRYPTION_KEY` est une clé AES-GCM indépendante de 32 octets encodée en base64 URL-safe. La sauvegarde contient les applications `accounts`, `homes` et `notifications`, donc les captures déjà chiffrées, les secrets chiffrés et les condensats de mots de passe. L’archive complète reçoit une seconde enveloppe AES-GCM.

```powershell
python manage.py backup_sentinelle C:\sauvegardes\sentinelle.backup
python manage.py restore_sentinelle C:\sauvegardes\sentinelle.backup
python manage.py restore_sentinelle C:\sauvegardes\sentinelle.backup --apply
```

Depuis octobre 2026, la sauvegarde couvre aussi `notifications` (preferences,
installations et livraisons push). La lecture des applications se fait dans une
transaction pour garder un instantane coherent. Sur ce PC, E: est une cle USB
amovible en exFAT : y placer des archives chiffrees horodatees, jamais la base
SQLite active ni l'unique copie des secrets. La commande refuse par defaut
d'ecraser une archive existante. `restore_sentinelle <archive>` sans `--apply`
verifie l'archive sans modifier les donnees. Conserver une seconde copie des
archives et la cle `BACKUP_ENCRYPTION_KEY` separement ; les clefs de donnees
restent necessaires pour relire captures et jetons apres restauration.

Sans `--apply`, la restauration vérifie l’authenticité et le JSON sans modifier la base. Conserver la clé hors du serveur et tester régulièrement la restauration sur une base isolée.

## Rotation des clés

1. Arrêter les écritures et créer une sauvegarde vérifiée avec l’ancienne clé de sauvegarde.
2. Restaurer cette archive dans un environnement isolé et vérifier le déchiffrement d’au moins une capture.
3. Pour `CAPTURE_ENCRYPTION_KEY`, `CAMERA_SOURCE_ENCRYPTION_KEY`, `EVENT_SIGNING_ENCRYPTION_KEY`, `MFA_ENCRYPTION_KEY` ou `BIOMETRIC_ENCRYPTION_KEY`, déchiffrer chaque valeur avec l’ancienne clé puis la rechiffrer avec la nouvelle en conservant son identifiant comme donnée associée.
4. Vérifier les captures, l’appairage caméra et le TOTP avant de déployer les nouvelles clés.
5. Pour `BACKUP_ENCRYPTION_KEY`, conserver l’ancienne clé jusqu’à expiration des archives créées avec elle ou restaurer puis recréer ces archives avec la nouvelle clé.
6. Révoquer l’ancienne clé seulement après sauvegarde, contrôle et retour arrière documenté.

Ne jamais remplacer directement une clé de chiffrement de données existantes : les valeurs deviendraient illisibles.
