# Publication du code pour YOLO

Sentinelle Maison est d'abord un projet academique non destine a la vente.
Cette finalite ne dispense pas des conditions AGPL-3.0 du modele YOLO11n.
La [position publiee par Ultralytics](https://www.ultralytics.com/license)
demande la mise a disposition du code source correspondant du projet qui
utilise ses modeles. La [section 13 de l'AGPL](https://www.gnu.org/licenses/agpl-3.0.en.html)
concerne aussi les utilisateurs qui interagissent avec le logiciel en reseau.
Il s'agit d'une procedure de publication, pas d'une attestation juridique.

## Avant la publication

1. Obtenir l'accord des titulaires de droits du code, notamment les quatre
   contributeurs initiaux cites dans `README.md`, et verifier les droits sur
   les documents, images et autres ressources. Ne pas relicencier les
   dependances tierces : conserver leurs notices et licences propres.
2. Auditer les fichiers suivis, non suivis **et l'historique Git** pour les
   secrets, comptes de service, bases, captures, biometrie, journaux et
   donnees personnelles. La presence de `.gitignore` ne nettoie pas l'historique.
   Faire tourner les cles deja divulguees avant toute publication.
3. Ajouter le texte officiel AGPL-3.0 et les mentions de droits du code que
   les auteurs autorisent a publier. Documenter provenance, licence et
   empreinte du poids YOLO, ainsi que les licences des autres composants.
4. Publier le **code source correspondant a la version servie**, y compris
   les modifications locales, scripts de construction et configurations
   expurgees de leurs valeurs secretes. Ni `.env` reel ni base de production
   ne doivent etre mis dans l'archive. Verifier que le commit et son archive
   sont accessibles anonymement avant de deployer.
5. Deployer cette meme revision, puis definir `SENTINELLE_SOURCE_REVISION`
   avec son SHA Git complet de 40 caracteres. Le pied de page affiche alors
   un lien telechargeable vers l'archive de cette revision. Controler le lien
   sans connexion et confirmer qu'il correspond au code en service. A chaque
   deploiement, mettre a jour le SHA et revalider le lien.

Le depot GitHub existe deja en public, mais la branche locale contient des
changements non publies. Un lien vers l'etat courant du depot ne suffirait
donc pas aujourd'hui. Tant que ces etapes ne sont pas achevees, le modele
reste `development_only` et aucun service webcam permanent ne doit etre
annonce comme conforme. Une revue juridique reste recommandee avant une
diffusion plus large.

## Revue preparee le 14 octobre 2026

`tools/prepare_source_release.py` a prepare sur E: une archive de revue
independante : `E:\CodexCaches\sentinelle-source-review-20261014-12`.
Elle contient 418 fichiers sources et son audit a examine 897 blobs de
l'historique Git. Le rapport ne signale aucune correspondance aux secrets
locaux connus ni aux motifs recherches ; ce resultat automatise ne remplace
pas la revue humaine. Les bases, fichiers `.env` reels, identites DPAPI,
caches, journaux, captures, biometrie, documents de passation et
configuration Cloudflare locale en sont exclus.

Le 14 octobre 2026, l'utilisateur a confirmé l'accord des quatre auteurs
nommés dans README pour cette publication AGPL-3.0. L'archive inclut le texte
AGPL-3.0, les notices de composants tiers et une
proposition de registre `production_approved` pour le poids YOLO qualifie.
Le depot de travail, le registre actuellement servi et la branche publique
n'ont pas ete modifies par cette preparation. La publication devra partir
de cette archive revue dans une branche source distincte, sans reecrire
l'historique de `master`, puis verifier anonymement l'archive du commit et
enregistrer son SHA complet dans le recu de deploiement.
