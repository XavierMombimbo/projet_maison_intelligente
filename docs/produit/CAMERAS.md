# Caméras réelles — compatibilité et qualification

Date : 24 septembre 2026. Aucun modèle de caméra IP n’a encore été qualifié pour Sentinelle Maison. Le code distingue webcam et RTSP, chiffre la configuration RTSP et limite chaque identité de passerelle à une caméra. CAM-002 fournit maintenant le client d’acquisition ; sa validation matérielle reste obligatoire.

## Cible initiale

Retenir une caméra IP alimentée en continu, accessible depuis une passerelle sur le même réseau, avec un flux RTSP H.264 documenté. Préférer un modèle disposant d’ONVIF Profile T pour la découverte/configuration lorsque la passerelle prendra ces fonctions en charge. ONVIF Profile T couvre notamment le streaming H.264/H.265 et certaines fonctions d’événements ; les fonctions exactes dépendent du produit. [ONVIF Profile T](https://www.onvif.org/profiles/profile-t/).

La conformité ONVIF se vérifie pour un modèle **et sa version de firmware**, dans le registre officiel. Une mention marketing ou la compatibilité d’une autre caméra de la même marque ne suffit pas. La qualification Sentinelle reste nécessaire, même pour un produit conforme. [Registre des produits conformes ONVIF](https://www.onvif.org/conformant-products/).

## Matrice de prise en charge prévue

| Source | État actuel | Cible du premier pilote |
|---|---|---|
| Webcam USB dans le navigateur | Implémentée | Conservée ; nécessite navigateur actif et permission utilisateur |
| Caméra IP RTSP H.264 | Client local, timeouts et reconnexion implémentés ; matériel non validé | Acquisition via passerelle locale et reconnexion automatique |
| Caméra ONVIF Profile T | Non intégrée | Découverte/profils de flux ; validation du flux réel obligatoire |
| Caméra ONVIF Profile S existante | Non intégrée | Évaluation au cas par cas via le flux RTSP disponible |
| Caméra H.265 uniquement | Non qualifiée | Hors cible initiale tant que décodage, charge et éventuel transcodage ne sont pas mesurés |
| NVR/DVR exposant un RTSP par canal | Non intégré | Possible après qualification individuelle des canaux, identifiants et limites de connexion |
| Caméra uniquement accessible par une app propriétaire | Non intégrée | Étude distincte si une API/SDK et ses conditions d’utilisation le permettent |
| Caméra sur batterie avec mise en veille | Non qualifiée | Hors cible initiale pour la surveillance continue |

Aucune marque n’est garantie compatible à ce stade. Le modèle possédé par l’utilisateur sera examiné avant de proposer du matériel supplémentaire.

## Informations nécessaires pour qualifier un appareil

| Information | Utilité |
|---|---|
| Marque, modèle exact, firmware | Référence reproductible et vérification ONVIF |
| RTSP documenté, codec et profils de flux | Décodage et choix d’un sous-flux adapté à l’analyse |
| Résolution, cadence et débit configurables | Mesure du compromis détection/charge/réseau |
| Alimentation, Ethernet/Wi-Fi/PoE | Continuité et conditions d’installation |
| Vision nocturne, champ de vision, emplacement | Essais de détection dans les conditions réellement surveillées |
| Authentification et compte de lecture dédié | Limiter l’accès aux seules fonctions nécessaires |
| Nombre de connexions simultanées | Coexistence avec NVR, app constructeur et passerelle |
| Capacité de fonctionnement sans cloud constructeur | Vérification du mode local lors d’une coupure Internet |

Les mots de passe et URL complètes contenant des secrets sont saisis dans la configuration protégée, jamais copiés dans cette fiche ou dans un ticket.

## Parcours d’ajout

1. Le propriétaire ajoute une caméra à sa maison et choisit `Webcam` ou `RTSP`.
2. Pour RTSP, il saisit l’adresse sans identifiants, puis l’utilisateur et le mot de passe dans les champs dédiés.
3. L’application accepte seulement `rtsp://` ou `rtsps://`, chiffre URL et identifiants avec AES-GCM et n’affiche ensuite que schéma, hôte, port et chemin.
4. L’appairage remet une identité à usage unique. Son JWT identifie une seule caméra ; changer l’identifiant dans une URL ne donne aucun accès à une autre caméra.
5. La révocation invalide les jetons, efface le secret d’appareil, la clé de signature et la configuration RTSP.

Le parcours CAM-002 est détaillé dans [PASSERELLE_RTSP.md](PASSERELLE_RTSP.md). CAM-003 ajoutera la découverte ONVIF et les contrôles réseau contre les accès arbitraires aux services locaux, loopback ou métadonnées d’infrastructure.

Les identifiants restent protégés dans le connecteur ; l’application mobile ne reçoit pas le mot de passe RTSP. L’analyse vidéo est locale par défaut. La consultation d’un direct distant pourra utiliser une passerelle média authentifiée et un transport adapté, dans un incrément distinct du premier pilote.

## Protocole de recette

| Essai | Résultat à consigner |
|---|---|
| Flux continu pendant 24 h | Nombre/durée des interruptions, images fraîches, CPU/RAM et débit |
| Débranchement et redémarrage caméra | Délai de détection hors ligne et de reconnexion, absence de doublons |
| Coupure Internet avec réseau local actif | Analyse/planning maintenus, capacité du tampon et synchronisation différée |
| Redémarrage de la passerelle | Reprise automatique, état courant du planning appliqué et événement d’interruption |
| Modification du mot de passe caméra | Erreur compréhensible, absence de boucle d’essais excessive, rétablissement après mise à jour |
| Jour/nuit et éclairage variable | Captures annotées, détections manquées et fausses alertes par classe |
| Lecture simultanée depuis un autre client | Comportement à la limite de connexions du modèle |
| Caméra révoquée / utilisateur sans droit | Refus de configuration, d’événement ou de capture selon l’identité concernée |
| MFA, planning et notification sur téléphone réel | Parcours complet et latences mesurées, pas seulement un test de lecture RTSP |

Pour chaque appareil, créer une fiche `modele + firmware + configuration de flux + matériel de passerelle + version logicielle + date + résultats + limites`. Marquer « qualifié » seulement après recette ; un changement de firmware ou de profil de flux déclenche une nouvelle vérification pertinente.

## État des qualifications

| Référence | Firmware | Passerelle | Résultat |
|---|---|---|---|
| À renseigner avec la première caméra pilote | À renseigner | À dimensionner après mesure | Non testée |
