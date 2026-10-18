# Estimation locale des postures

État au **18 octobre 2026**. POSE-001 dispose d'un banc d'essai local
YOLO11 Pose. Il est indépendant de la surveillance permanente et n'envoie
aucun événement. RTMPose reste exclu ; les poids OpenPose officiels restent
inaccessibles depuis ce poste (délais HTTP et connexion HTTPS interrompue
sur le serveur SNU indiqué par les scripts officiels).

## Banc d'essai YOLO11 Pose

Le modèle ONNX officiel `yolo11n-pose.onnx`, diffusé par Ultralytics dans
`assets/v8.3.0`, est sous AGPL-3.0. Ses métadonnées indiquent un export
Ultralytics 8.3.238, une entrée RGB 640 × 640 et les 17 articulations COCO.
Cette recette volontaire s'inscrit dans le projet académique et le cadre
AGPL déjà retenus. Elle ne constitue pas une activation en production ;
une future version servie devra suivre la publication de source habituelle.

Les poids restent hors Git sous `E:\CodexCaches\sentinelle-pose-20261018` :
**11 853 451 octets**, SHA-256
`93e2866b0ce678f99b4dd88af0c12e9ea2edf079a361dc2ecbc6226b77ff6408`,
identique au digest de l'asset GitHub officiel. Le registre les marque
`academic_approved`. Le chargement exige une activation explicite et
contrôle le manifeste, la taille, l'empreinte et le contrat ONNX.

`gateway/yolo_pose.py` restaure les coordonnées après redimensionnement,
masque les articulations hors image, supprime les doublons et associe au
plus un squelette à chaque piste. Une association ambiguë ou absente rend
le résultat incertain. `gateway/pose_recipe.py` n'utilise aucune identité
de caméra ni API ; il ne conserve que des compteurs et des mesures.

Recette bornée : fermer tout aperçu navigateur, se placer seul et éclairé,
puis lancer depuis la racine :

```powershell
.\.venv\Scripts\python.exe -m gateway.pose_recipe `
  --model-root E:\CodexCaches\sentinelle-pose-20261018 `
  --academic-use-acknowledged --seconds 20 `
  --output E:\CodexCaches\sentinelle-pose-20261018\recipe.json
```

Si une passerelle occupe la webcam, préparer sa restauration avant de
l'interrompre. Au début de l'essai du 18 octobre, la tâche permanente était
déjà désactivée, son statut était `configuration_refused` et aucun processus
Python de passerelle ne tournait. Cette recette n'a pas changé cet état.

Résultat réel avec le cadrage annoncé par l'utilisateur (haut du corps) :
40 images en 20 s, une personne présente sur les 40 ; **40 résultats
`uncertain` / `torso_partially_hidden`**. Médiane d'inférence **203,75 ms**,
95e centile **368,93 ms**, pic mémoire du processus **193,27 Mo** et
**21,453 s CPU** (107,26 % d'un cœur à la cadence demandée de 2 Hz).
Aucune image enregistrée, aucun événement envoyé.

Ce résultat valide le fonctionnement du modèle et la prudence sur ce
cadrage, pas les états du corps entier. POSE-001 est **À valider pour ce
banc isolé** ; ne pas clore la qualification complète sur cette seule
recette. Tester ensuite debout, bas et horizontal avec hanches, genoux et pieds visibles,
puis distance, occlusions, plusieurs personnes et éclairages différents.
Ne pas provoquer de chute pour la recette ; horizontal se teste seulement
dans une position volontaire et confortable si le cadrage le permet.

Sources officielles : [modèles YOLO11](https://docs.ultralytics.com/models/yolo11/),
[asset et digest](https://github.com/ultralytics/assets/releases/tag/v8.3.0),
[licence des modèles](https://www.ultralytics.com/license),
[scripts OpenPose](https://github.com/CMU-Perceptual-Computing-Lab/openpose/blob/master/models/getModels.sh).

## Vocabulaire produit

La passerelle décrit uniquement une géométrie corporelle :

- `upright` : torse vertical et au moins une jambe suffisamment visible et étendue ;
- `low` : géométrie basse avec genoux pliés ;
- `horizontal` : torse et étendue corporelle principalement horizontaux ;
- `uncertain` : articulations masquées, qualité insuffisante ou géométrie ambiguë.

Ces états ne signifient ni chute, ni malaise, ni comportement hostile. Une décision de ce type demanderait un suivi temporel, du contexte et une validation terrain séparée.

## Contrat de passerelle

`gateway/pose.py` reçoit les boîtes des personnes déjà suivies et conserve leur `track_id`. RTMPose produit les 17 articulations COCO ; le classificateur géométrique garde explicitement les résultats incertains. Plusieurs personnes sont évaluées séparément.

L'ancien adaptateur RTMPose reste fermé par défaut : son checkpoint doit
porter le statut `production_approved` avec taille et SHA-256 conformes.
MMPose reste optionnel et n'a pas été installé. L'adaptateur YOLO11 Pose
distinct applique les contrôles de recette académique décrits ci-dessus.

## Blocage des poids publics

Le dépôt MMPose est publié sous Apache-2.0 et son registre officiel associe RTMPose-S au checkpoint `8edcf0d7`. En revanche, aucun document officiel ne précise actuellement la licence applicable à ce fichier de poids et sa lignée inclut un préentraînement AIC. La demande officielle `open-mmlab/mmpose#3273` est toujours ouverte.

Sentinelle ne télécharge donc pas ce checkpoint et ne le considère pas comme utilisable dans un produit propriétaire. POSE-001 restera bloquée jusqu’à l’une des conditions suivantes :

1. confirmation écrite d’OpenMMLab pour le checkpoint exact ;
2. checkpoint alternatif avec licence commerciale explicite et provenance documentée ;
3. entraînement interne sur des données dont les droits sont documentés.

Sources officielles :

- https://github.com/open-mmlab/mmpose
- https://github.com/open-mmlab/mmpose/blob/main/configs/body_2d_keypoint/rtmpose/coco/rtmpose_coco.yml
- https://github.com/open-mmlab/mmpose/issues/3273

## Validation restante

Après approbation d’un poids, il faudra enregistrer l’artefact et son empreinte, installer MMPose sur la passerelle, puis mesurer jour/nuit, distance, occlusions, plusieurs personnes, latence, CPU et mémoire. Aucune simulation ne remplacera cette recette réelle.
