# Évaluation et calibration terrain

## Principe

Les scènes utilisées pour modifier les seuils appartiennent à la partition **Ajustement**. Les scènes qui servent à mesurer le résultat final appartiennent à la partition **Évaluation indépendante**. Une même campagne ne peut pas appartenir aux deux partitions.

Chaque campagne concerne une caméra réelle et une condition principale : jour, nuit, ombres, pluie ou occlusion. Une seule campagne peut être active par caméra. Le début, la fin, la durée et le nombre d’événements réels sont conservés.

## Première recette

1. Ouvrir la fiche de la caméra `chrome`, puis **Évaluation terrain**.
2. Choisir **Évaluation indépendante** et **Jour**.
3. Démarrer la mesure, puis utiliser le bouton **Ouvrir le mode caméra pour chrome** afin de conserver la même caméra.
4. Produire au moins un événement réel. Si cette caméra n’est pas appairée dans le navigateur, l’écran le signale et demande son appairage.
5. Revenir à l’évaluation terrain et arrêter la campagne.
6. Vérifier que la campagne terminée affiche une durée et au moins un événement.

## Annotation et métriques

Une campagne terminée peut être annotée pour les classes personne, chien et chat. Pour chaque classe, saisir :

- **Attendues** : occurrences réellement présentes dans les scènes ;
- **Correctes** : occurrences attendues que l’IA a détectées ;
- **Fausses** : détections annoncées alors que l’objet était absent.

La précision vaut `correctes / (correctes + fausses)`. Le rappel vaut `correctes / attendues`. Une valeur sans dénominateur est affichée `—`. Les rapports **Ajustement des seuils** et **Évaluation indépendante** sont calculés séparément.

Les fausses alertes par caméra-heure valent `total des fausses détections / durée annotée en heures`. Seules les campagnes dont les trois classes sont annotées entrent dans ce calcul.

Le CPU moyen et le pic mémoire du navigateur sont relevés pendant la campagne dans le gestionnaire des tâches de Chrome (`Maj+Échap`), puis inscrits dans l’annotation. Le rapport affiche un CPU moyen pondéré par la durée et le plus grand pic mémoire de chaque partition.

### Recette de l’étape 2

1. Sur la campagne `chrome` de 26 secondes, cliquer **Annoter**.
2. Examiner l’événement de la campagne et sa capture.
3. Saisir les nombres réels pour personne, chien et chat, puis enregistrer.
4. Vérifier que le rapport **Évaluation indépendante** affiche les mêmes totaux et les pourcentages attendus.

### Recette de l’étape 3

1. Démarrer une nouvelle campagne réelle d’environ une minute.
2. Pendant l’analyse, ouvrir le gestionnaire des tâches de Chrome avec `Maj+Échap` et noter le CPU approximatif et le plus grand usage mémoire du processus actif.
3. Arrêter puis annoter la campagne, y compris les deux mesures de performance.
4. Vérifier dans le rapport la durée annotée, les fausses alertes par heure, le CPU moyen et le pic RAM.

Validation obtenue le 26 septembre 2026 sur `chrome` : 0,079 h annotée, 0 fausse alerte/h, CPU observé 0,0 %, pic RAM 219 Mo et 2 personnes correctement détectées sur 2.

Condition **Ombres** validée le 26 septembre 2026 : campagne de 291 s avec une personne correctement détectée. Le cumul d’évaluation indépendante atteint 0,160 h, 3 personnes correctes sur 3 et aucune fausse alerte.

Condition **Nuit** validée le 26 septembre 2026 : campagne de 58 s avec une personne correctement détectée à 83 % de confiance. Le cumul atteint 0,176 h, 4 personnes correctes sur 4 et aucune fausse alerte.

Condition **Pluie** validée le 26 septembre 2026 : campagne de 1 103 s, événement réel `502b1f56-bbee-4279-b162-300883c2ded9` et une personne correctement détectée à 88 % de confiance. Le cumul atteint 0,482 h, 5 personnes correctes sur 5 et aucune fausse alerte.

Condition **Occlusion** validée le 26 septembre 2026 : campagne de 60 s, événement réel `9c2cd1a0-d0b8-4ea7-a606-27051caba0bf` et une personne correctement détectée à 82 % de confiance. Le cumul final atteint 0,499 h, 6 personnes correctes sur 6, 100 % de précision et de rappel, et aucune fausse alerte.

## Étapes suivantes

- compléter progressivement le jeu d'évaluation avec davantage de personnes, d'animaux et de scènes difficiles avant tout ajustement des seuils.
