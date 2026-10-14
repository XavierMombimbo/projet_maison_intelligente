# Suivi temporel et zones configurables

AI-002 ajoute une configuration d’analyse propre à chaque caméra et un suivi local léger des objets détectés. L’identifiant de piste relie les observations successives dans une scène ; il n’identifie ni une personne ni un animal.

## Configuration

- La zone rectangulaire utilise quatre coordonnées normalisées : `x`, `y`, `width`, `height`, comprises dans l’image entre 0 et 1.
- La ligne facultative utilise `x1`, `y1`, `x2`, `y2`. Elle est affichée comme repère et prépare les règles de franchissement d’AI-003.
- La durée de présence accepte 0,5 à 30 secondes.
- L’interface propriétaire saisit les coordonnées en pourcentage pour éviter les décimales difficiles à manipuler.
- La configuration est renvoyée uniquement à la caméra authentifiée par son endpoint d’état.

La zone complète vaut `0, 0, 100, 100`. Une boîte appartient à la zone lorsque son centre s’y trouve.

## Suivi local

Les boîtes sont associées uniquement entre objets de même classe, par recouvrement et proximité du centre. Une piste tolère une interruption maximale de 1,2 seconde. La présence continue dans la zone est calculée avec une horloge monotone, en secondes, et non avec un nombre d’images. Les tests couvrent une analyse rapide à 10 images par seconde et une analyse lente à 2 images par seconde : l’événement devient admissible après la même durée réelle.

Les événements v2 transportent l’identifiant `track_id`. La page de détail l’affiche avec la classe et le score. La ligne de référence n’engendre pas encore d’alerte ; les règles de direction et de franchissement appartiennent à AI-003.

## Recette manuelle

1. Sur la page de surveillance, cliquer sur **Configurer la zone de cette caméra**.
2. Saisir `25`, `20`, `50`, `60` pour gauche, haut, largeur et hauteur ; choisir une durée de `2,0` secondes.
3. Activer la ligne avec les points `50, 0` et `50, 100`, puis enregistrer.
4. Revenir à la surveillance et démarrer la webcam. Un rectangle cyan et une ligne rose doivent apparaître.
5. Rester hors du rectangle : aucune piste ne doit atteindre la durée.
6. Entrer dans le rectangle : le même numéro de piste doit rester visible et le compteur doit atteindre 2,0 secondes avant l’événement.
7. Ouvrir l’événement et vérifier la présence de `piste track-N`.
