# Détection multiclasse locale

AI-001 étend l’analyse webcam locale aux classes COCO `person`, `dog` et `cat`. Une détection ne constitue pas une identification individuelle de la personne ou de l’animal.

## Politique active

| Classe événement | Libellé affiché | Indice COCO | Seuil |
|---|---|---:|---:|
| `person` | Personne | 0 | 0,45 |
| `dog` | Chien | 16 | 0,50 |
| `cat` | Chat | 15 | 0,50 |

La suppression des boîtes en double s’applique séparément à chaque classe. Une personne et un animal qui se chevauchent restent donc tous deux dans l’événement v2. Jusqu’à 64 objets acceptés sont conservés.

YOLO11n 320 ONNX reste le modèle de développement local. COCO-SSD sert de repli si son chargement aboutit. Si aucun modèle ne peut fonctionner ou si l’inférence échoue, l’interface affiche `Indisponible — aucune détection` et n’envoie aucun événement ; l’aperçu webcam peut rester actif.

## Recette manuelle

1. Ouvrir `/camera/surveillance/`, puis démarrer la webcam.
2. Vérifier que le modèle indique `personne, chien, chat`.
3. Présenter successivement une personne, une photo nette de chien, puis une photo nette de chat devant la webcam.
4. Vérifier le libellé, la boîte et le score affichés, puis ouvrir les événements créés et contrôler leurs classes.
5. Présenter une image contenant une personne et un animal ; vérifier que les deux classes figurent dans le même événement lorsque leurs scores dépassent les seuils.

La recette mesure seulement le bon fonctionnement du parcours. La précision par classe, de jour et de nuit, devra être évaluée sur un jeu d’images annoté avant le pilote.
