# Réception idempotente et boîte d’envoi

## Idempotence

Chaque caméra produit un `event_id`. Le serveur calcule une empreinte SHA-256 du contenu métier signé : caméra, identifiant, version du contrat, observation, modèle, objets et capture.

- Première réception : création de l’événement et réponse HTTP `201` avec `deduplicated=false`.
- Retransmission identique avec un nouveau nonce signé : aucun doublon, réponse HTTP `200` avec `deduplicated=true` et le même identifiant serveur.
- Même `event_id` avec un contenu différent : réponse HTTP `409` et audit `camera.detection.idempotency_conflict`.
- Une signature ou un nonce invalide reste refusé avant l’idempotence.

## Boîte d’envoi transactionnelle

La ligne `EvenementBoiteEnvoi` est créée dans la même transaction que l’événement, ses objets et sa capture chiffrée. Une alerte ne peut donc pas être validée en base sans travail de livraison associé.

La livraison immédiate est tentée après le commit. En cas d’arrêt du processus ou d’indisponibilité de Channels/Redis, la ligne reste `pending`. Les signaux de présence des caméras reprennent automatiquement jusqu’à 20 lignes en attente. Une reprise opérateur est aussi disponible :

```powershell
python manage.py dispatch_event_outbox --limit 100
```

Une livraison peut être répétée si le processus s’arrête après l’envoi mais avant l’enregistrement de `sent`. Les consommateurs dédupliquent avec l’identifiant serveur de l’événement. Le mécanisme garantit ainsi une livraison au moins une fois sans perdre l’alerte.

## Exploitation

L’administration Django affiche le statut, le nombre de tentatives, la dernière erreur et l’heure d’envoi. Une ligne `pending` avec une erreur persistante indique un problème de couche Channels/Redis à corriger avant de relancer la commande.
