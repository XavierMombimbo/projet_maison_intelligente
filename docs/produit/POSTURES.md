# Estimation locale des postures

État au **4 octobre 2026**. POSE-001 prépare l’analyse locale des articulations sans activer de checkpoint dont les droits ne sont pas établis.

## Vocabulaire produit

La passerelle décrit uniquement une géométrie corporelle :

- `upright` : torse vertical et au moins une jambe suffisamment visible et étendue ;
- `low` : géométrie basse avec genoux pliés ;
- `horizontal` : torse et étendue corporelle principalement horizontaux ;
- `uncertain` : articulations masquées, qualité insuffisante ou géométrie ambiguë.

Ces états ne signifient ni chute, ni malaise, ni comportement hostile. Une décision de ce type demanderait un suivi temporel, du contexte et une validation terrain séparée.

## Contrat de passerelle

`gateway/pose.py` reçoit les boîtes des personnes déjà suivies et conserve leur `track_id`. RTMPose produit les 17 articulations COCO ; le classificateur géométrique garde explicitement les résultats incertains. Plusieurs personnes sont évaluées séparément.

Le chargement est fermé par défaut : le checkpoint doit être présent dans `config/model_registry.json`, porter le statut `production_approved`, déclarer sa taille et son SHA-256, puis correspondre exactement au fichier local. MMPose reste une dépendance optionnelle tant qu’aucun poids n’est approuvé.

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
