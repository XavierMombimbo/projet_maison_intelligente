# Contrat d’événement v2

Le point d’entrée reste `POST /api/camera/me/detections/` en `multipart/form-data`. Une caméra v1 peut continuer à envoyer `event_id`, `confidence`, `simulated=false` et `capture`. Une caméra v2 envoie les champs suivants :

| Champ | Règle |
|---|---|
| `contract_version` | entier égal à `2` |
| `event_id` | UUID unique produit par la caméra |
| `observed_at` | date ISO 8601 avec fuseau, moment de l’observation |
| `model_name`, `model_version` | 1 à 80 caractères ASCII autorisés |
| `objects` | JSON de 1 à 64 objets |
| `rule_context` | JSON facultatif décrivant la règle locale ayant déclenché l’événement |
| `simulated` | doit être `false` ; `true` est refusé |
| `capture` | JPEG, PNG ou WebP selon les limites serveur |

Chaque objet contient `label`, `confidence`, `bbox` et éventuellement `track_id`. `label` fait au plus 64 caractères. `confidence` est compris entre 0 et 1. `bbox` contient `[x, y, largeur, hauteur]`, normalisé entre 0 et 1 et entièrement contenu dans l’image. Les champs inconnus sont refusés.

Le contexte de règle contient `id`, `version`, `type`, `duration_seconds`, `zone`, `line`, `direction` et `track_ids`. Les types actuels sont `presence_prolonged` et `line_crossing`. La zone et la ligne utilisent des coordonnées normalisées et validées. Une règle de franchissement exige une ligne et une direction.

Le serveur conserve `observed_at` séparément de l’heure de réception. Le nom et la version du modèle sont attachés à l’événement, et les objets sont stockés séparément pour les requêtes futures. L’ancien champ `horodatage` reste l’heure de réception afin de conserver l’historique v1.

Le champ `simulated` reste dans le message signé pour préserver la forme canonique des clients déjà développés. Il vaut toujours `false` : aucun événement simulé ne peut être créé.

## Signature

La signature est un HMAC-SHA-256 hexadécimal envoyé dans `X-Camera-Signature`. Le message canonique v2 contient, dans cet ordre : identifiant de contrat, méthode, chemin, caméra, horodatage de requête, nonce, événement, observation UTC, modèle, version, objets canoniques, simulation, type MIME et SHA-256 de la capture. Les nombres des objets utilisent six décimales et les objets sont triés de façon déterministe. Lorsqu’un contexte de règle est présent, le marqueur `sentinelle-rule-context-v1` et sa forme canonique sont ajoutés à la fin. Un client v2 sans règle conserve donc exactement sa signature antérieure.

Le code de référence se trouve dans `homes/request_signing.py` et `static/js/event-contract-v2.js`.

## Vecteur Python ↔ JavaScript

- clé : `vector-key-2026`
- caméra : `11111111-1111-4111-8111-111111111111`
- nonce : `22222222-2222-4222-8222-222222222222`
- événement : `33333333-3333-4333-8333-333333333333`
- requête : `1790150400`
- observation : `2026-09-23T08:00:00.123Z`
- modèle : `yolo11n`, version `320@18eac4f9d291`
- objets : personne `0.9123456`, boîte `[0.1,0.2,0.3,0.4]`, suivi `p-1`; chien `0.8`, boîte `[0.5,0.6,0.2,0.3]`
- type : `image/jpeg`; empreinte de capture : 64 caractères `a`
- SHA-256 du message canonique : `bb156ca0a941542e9bd842e73c248594f654a4d9b0f22267db89b0f103fb4176`
- HMAC attendu : `7a908759967ee766142a238eb633d0be7649d18f899bd7c01830a8d06b167c35`

Ce vecteur est vérifié par la suite Django et par le module JavaScript avec Node pendant la validation d’EVT-001.

Un second vecteur couvre `line-crossing` version 1 avec durée `1.25`, zone `[0.1, 0.2, 0.7, 0.6]`, ligne verticale centrale, direction `negative_to_positive` et pistes `track-1`, `track-2`. Avec le modèle `yolo11n` version `320@test` et un objet personne suivi par `track-1`, le HMAC attendu est `e650616b10356be84a7b1c84bd94a2afc7351706ca6100964d539be63c6ab50c`.
