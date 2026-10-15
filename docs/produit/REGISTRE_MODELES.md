# Registre des modèles et décisions techniques

État au **24 septembre 2026**. Le fichier machine `config/model_registry.json` est la source des versions, origines, statuts et empreintes. Tout nouveau poids doit être ajouté avec sa licence, sa taille et son SHA-256 avant intégration.

## Décisions proposées pour le produit

- **Distribution actuelle :** projet academique non destine a la vente. La voie retenue pour conserver YOLO sans licence Enterprise est la publication conforme AGPL-3.0, sous reserve des droits des contributeurs, de l'audit des secrets et de la publication de la version exacte servie. Voir [CONFORMITE_AGPL.md](CONFORMITE_AGPL.md). Une commercialisation ulterieure demanderait une nouvelle decision.
- **Calcul :** l'analyse reste sur la passerelle de la maison. Le serveur reçoit les événements signés et les captures utiles, pas le flux vidéo continu.
- **Mobile :** Flutter, Android en premier. Le code restera compatible iOS, dont les builds nécessitent macOS/Xcode. Flutter est sous BSD-3-Clause et prend en charge Android et iOS.
- **Objets et animaux :** conserver YOLO11n uniquement pour le développement actuel. Évaluer **RF-DETR Nano 1.10.1** comme candidat de production permissif pour `person`, `dog`, `cat` et les classes COCO utiles.
- **Visages :** la recette FACE-002 utilise InsightFace 0.7.3 et ArcFace `buffalo_l` uniquement pour le projet académique non commercial confirmé. Les poids publics InsightFace restent interdits pour un produit commercial ; ils sont hors Git sur E:, hachés fichier par fichier dans le registre, et aucun visage brut n’est conservé.
- **Postures, gestes et actions :** RTMPose puis MediaPipe sont les premiers candidats. MMAction2 reste expérimental jusqu'à définition des actions, des données et du matériel.

## État des composants

| Composant | Statut | Motif principal |
|---|---|---|
| YOLO11n 320 ONNX | Développement seulement | Modèle local et vérifié, mais AGPL-3.0 sauf licence Enterprise |
| COCO-SSD 2.2.3 | Bloqué | Le code est local, mais les poids de repli ne sont ni vendorizés ni hachés |
| RF-DETR Nano 1.10.1 | Candidat production | Paquet et poids Nano désignés Apache-2.0 ; benchmark passerelle requis |
| InsightFace 0.7.3 / ArcFace `buffalo_l` | Approuvé académique | Code MIT ; poids publics réservés à la recherche non commerciale, empreintes vérifiées avant usage |
| ByteTrack | Candidat | Suivi MIT sans poids ; commit à figer lors de l'intégration |
| RTMPose / MMPose 1.3.2 | Candidat | Code Apache-2.0 ; vérifier séparément checkpoint et données |
| MediaPipe 1.0.1 | Candidat | Code Apache-2.0 ; figer le bundle de tâche et traiter la télémétrie |
| MMAction2 1.2.0 | Évaluation | Code Apache-2.0 ; classes, poids, données et GPU restent à choisir |

## Artefacts déjà présents

| Fichier | Taille | SHA-256 |
|---|---:|---|
| `static/vendor/yolo/yolo11n.onnx` | 10 594 049 | `ed25687f7f3176a041bcdd0173501629afcaaddf37711f2294ced377f249fd65` |
| `static/vendor/yolo/ort.wasm.min.js` | 50 026 | `2ec7579b2bbdef8e355f442b96dfb0bc1b18ca5729664cd692cd80ff4ea191eb` |
| `static/vendor/yolo/ort-wasm-simd-threaded.wasm` | 12 361 745 | `be0e129949062ad50290ef94683fac8be5bb6156f709e030b7a5f1661a2f6c17` |
| `static/vendor/tf-4.22.0.min.js` | 1 469 808 | `39ffff6e8c733b1d17957479c59f2ef2819fea4e5ebd56aaa832537e758f26e8` |
| `static/vendor/coco-ssd-2.2.3.min.js` | 9 258 | `95a1abd543043e4606b301bdc85fbd378e50747cc6d84d077192fa2a69fe18ea` |

Le pilote actuel a validé un flux webcam réel avec YOLO11n 320 dans le navigateur sur un Dell Latitude 5400. Cette preuve fonctionnelle ne mesure pas encore débit, consommation, précision ou nombre de flux simultanés.

## Conditions avant adoption

1. Télécharger depuis l'origine approuvée, stocker hors Git si nécessaire et calculer le SHA-256.
2. Archiver la licence exacte du code, des poids et des données d'entraînement.
3. Tester sur le matériel cible : jour/nuit, distance, occultation, plusieurs personnes et coupures réseau.
4. Mesurer latence, mémoire, débit et faux positifs par classe ; conserver un résultat `inconnu` ou `indisponible`.
5. Enregistrer le nom et la version du modèle dans chaque événement v2.

## Sources officielles

- [Licence Ultralytics](https://www.ultralytics.com/license)
- [InsightFace Model Zoo](https://github.com/deepinsight/insightface/blob/master/python-package/docs/model_zoo.md)
- [RF-DETR 1.10.1](https://pypi.org/project/rfdetr/1.10.1/)
- [ByteTrack](https://github.com/FoundationVision/ByteTrack)
- [MMPose](https://github.com/open-mmlab/mmpose)
- [MediaPipe](https://github.com/google-ai-edge/mediapipe)
- [MMAction2](https://github.com/open-mmlab/mmaction2)
- [Flutter FAQ](https://docs.flutter.dev/resources/faq)
