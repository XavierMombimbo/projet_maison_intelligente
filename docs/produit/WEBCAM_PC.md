# Webcam du PC sans navigateur

## Isolation du mode caméra du navigateur

Le mode web exige une connexion et contrôle les caméras autorisées du compte
avant de sélectionner un appairage local. Une caméra visible sans droit de
contrôle ne suffit pas. Chaque jeton du navigateur est lié à la session web,
vérifiée à chaque requête ; perte de droits, déconnexion ou changement de
compte invalident cet accès. Les POST conservent la protection CSRF et la
signature des événements.

Le navigateur conserve uniquement l'identifiant de caméra et la date
d'appairage, jamais le secret appareil, le jeton ou la clé de signature.
À la première lecture, les anciennes entrées sont expurgées de leurs secrets
et filtrées selon les droits du compte. Les jetons courts et clés nécessaires
restent en mémoire. Un ancien onglet est arrêté et son affichage effacé lors
d'un changement de session, y compris depuis un autre onglet ; le serveur
refuse aussi tout ancien jeton navigateur rejoué dans un autre compte.

Le parcours d'appairage web exige un compte autorisé et ne consomme pas le
code d'une caméra étrangère. L'API dédiée aux passerelles autonomes conserve
son authentification appareil indépendante ; leurs identités DPAPI ne sont
ni effacées ni révoquées par cette migration du navigateur. Les anciens jetons
appareil sont refusés dans les requêtes de navigateur : le mode web obtient
désormais son autorisation depuis la session connectée.

## Service PC autonome

Le mode `gateway webcam` capture la webcam locale avec OpenCV, execute
YOLO11n dans le processus PC, applique la presence dans la zone configuree,
envoie les evenements signes a l'API existante et publie un heartbeat d'analyse.
Il ne demarre pas automatiquement et n'interrompt pas la production web.

## Prerequis et essai

Une camera Sentinelle ne peut etre appairee qu'a un appareil. Creer une
**nouvelle** camera `Webcam PC` dans une maison existante puis generer son
code d'appairage. Ne pas reappairer la camera utilisee par le navigateur.
Fermer la webcam dans le navigateur avant le test : Windows ne garantit pas
que deux processus puissent l'ouvrir simultanement.
Si l'ancienne camera navigateur reste declaree active mais ne tourne plus,
desactiver seulement sa surveillance dans l'interface pour que le diagnostic
ne la compte pas comme une seconde analyse attendue. Ne pas la supprimer.

```powershell
.\.venv\Scripts\python.exe -m pip install -r gateway\requirements-webcam.txt
.\.venv\Scripts\python.exe -m gateway pair --server http://127.0.0.1:8001
.\.venv\Scripts\python.exe -m gateway webcam --once --allow-development-model
.\.venv\Scripts\python.exe -m gateway webcam --allow-development-model
```

La commande `pair` demande le code sans l'afficher et chiffre l'identite
locale avec DPAPI. `--once` lit une image et confirme l'inference, sans
transmettre d'evenement. La commande continue se termine avec Ctrl+C et
reessaie apres une indisponibilite de la webcam ou du serveur. Les images
restent en memoire jusqu'a une detection admissible ; la capture de l'alerte
est transmise via loopback local ou HTTPS et chiffree selon le circuit
existant du serveur.
Sur le PC qui heberge Sentinelle, la passerelle contacte `127.0.0.1:8001`
directement : le port reste lie a loopback et ne traverse pas Cloudflare.
Le client pose l'en-tete de protocole attendu par Django uniquement pour
une URL HTTP loopback. Hors du PC serveur, conserver HTTPS. Ne pas ouvrir
le port 8001 sur le reseau ni desactiver la redirection HTTPS publique.

## Demarrage Windows prepare

`gateway/install_windows_startup.ps1` installe une tache planifiee par
utilisateur, avec declencheur a l'ouverture de session et une seule instance.
Le lanceur garde hors du depot son identite DPAPI, son statut minimal et sa
configuration locale. Il attend le disque de cache configure (E: pour cette
installation) et ne substitue jamais un cache local si ce disque manque.

La tache permanente `SentinelleMaisonGateway` est installee **desactivee**.
Elle ne peut pas demarrer tant que le recu de publication, le manifeste de la
revision servie et `SENTINELLE_SOURCE_REVISION` ne correspondent pas
exactement. Le lanceur desactive sa propre tache apres un refus de
configuration ou de publication. Les messages et le statut local ne
contiennent ni URL de camera, ni jeton, ni secret.

Une tache de recette distincte `SentinelleMaisonRecipeStartup20261014` a ete
executee une fois par le Planificateur avec l'identite locale de production :
resultat 0, etat `completed_recipe`, une seule image analysee et aucune
alerte. Elle reste activee uniquement pour verifier le prochain vrai
demarrage Windows. Cette preuve a reussi le 14 octobre : declencheur de
session, redemarrage reel, statut post-demarrage et resultat 0. Elle attend
l'API locale jusqu'a une minute, afin que le demarrage de Daphne ne fasse pas
echouer la recette. Pour recontroler apres un futur redemarrage, executer :

```powershell
.\gateway\verify_windows_startup.ps1 -TaskName SentinelleMaisonRecipeStartup20261014
```

La preuve n'est positive que si l'horodatage de recette est posterieur au
demarrage Windows, la tache a le declencheur attendu, son resultat vaut 0 et
son statut est `completed_recipe`. Un lancement manuel ne suffit pas.

## Limites avant exploitation permanente

- Seules les classes personne, chien et chat et la regle de presence dans la
  zone sont prises en charge. Une ligne de franchissement configuree bloque
  volontairement le mode webcam plutot que de promettre une regle absente.
- Le suivi geometrique attribue maintenant une piste distincte par objet,
  avec association par recouvrement/proximite et au plus 64 pistes. La duree
  de presence appartient a la piste, pas a la classe : une seconde personne
  ne reprend pas automatiquement le temps de la premiere. Une absence dans
  l'image ou une sortie de zone remet sa duree a zero ; la piste expire apres
  1,2 s sans observation. Un arret de surveillance efface les pistes et un
  nouveau processus ne reutilise pas leurs identifiants. Ce suivi n'identifie
  personne ; croisements, occlusions et faible cadence restent a calibrer.
- Les evenements detectes sont chiffres avec Windows DPAPI avant leur premier
  envoi dans `%LOCALAPPDATA%/SentinelleMaison/webcam-events/<camera-id>`.
  La file contient au plus 20 evenements par camera, chacun avec une capture
  de 2 Mio maximum. Apres une reponse serveur perdue ou un echec d'envoi,
  le meme identifiant et la meme heure d'observation sont rejoues, mais la
  signature, le nonce et le jeton sont renouveles. Le fichier est retire
  uniquement apres acceptation du serveur. Une file pleine ou illisible
  arrete la passerelle et demande une intervention, sans effacer les preuves.
  Si l'observation date de plus de 60 s au moment de la reception, le serveur
  conserve l'evenement dans l'historique sans notification ni sirene tardive.
  Avec SCH-002, une copie de planning deja synchronisee, signee et chiffree
  permet de poursuivre l'analyse et d'appliquer les horaires hors ligne.
  Sans cette copie, aucune analyse hors ligne ne commence. Un refus HTTP
  401/403 efface le planning et arrete la passerelle sans relance automatique,
  tout en conservant les evenements en attente. La recette locale isolee
  utilise `--credentials-file` : voir [PLANNINGS.md](PLANNINGS.md).
- Recette reelle CAM-004 du 14 octobre reussie : 72 images webcam avec
  YOLO11n, backend isole 8002 et file DPAPI sur E:. Reponse TCP perdue apres
  reception 201, reprise 200 avec nonce neuf, un seul evenement/outbox ;
  second POST coupe avant serveur et attente reelle >63 s, historique sans
  outbox ni push tardif. Heure d'observation preservee et file finale vide.
  Preuve `E:\CodexCaches\sentinelle-cam004-20261014\result.json`.
  Resultats acceptes par l'utilisateur le 14 octobre (« Validons les pour
  passer ») ; CAM-004 cloturee pour tampon/sante sur webcam PC. La recette
  RTSP et le service permanent restent dans leurs cartes distinctes.
  Les captures protegees ont ete relues uniquement en memoire. Les premieres
  captures etaient noires/alterees ; l'utilisateur a ensuite arrete le mode
  camera navigateur avec « Arreter immediatement » et ferme l'onglet.
  Eviter de capturer simultanement dans le navigateur et OpenCV. Permissions
  Windows Allow, aucun pilote ou reglage change. Ne pas conclure a une panne
  du modele sans image exploitable. Aucun exemple artificiel utilise.
  `tmp/validate_cam004_live.py` attend jusqu'a 60 s la presence, mesure la
  luminosite sans conserver de photo brute et rouvre sa seule capture si
  presque noire ; il refuse une nouvelle recette si cette identite a deja
  produit des evenements. Production et notifications telephone preservees.
- Le modele actuellement integre est marque `development_only` dans
  `config/model_registry.json`. Le drapeau `--allow-development-model` est
  reserve a un essai explicite ; ne pas installer ce mode comme service de
  production avant publication conforme du code source. [Ultralytics](https://www.ultralytics.com/license)
  indique que ses modeles entraines relevent par defaut de l'AGPL-3.0 et
  propose une licence Enterprise pour un produit proprietaire. Si le projet
  reste ferme sans cette licence, evaluer un autre modele et ses poids :
  [RF-DETR Nano](https://github.com/roboflow/rf-detr/blob/develop/docs/index.md)
  est annonce sous Apache 2.0, mais n'est ni integre ni qualifie sur ce PC.
  Conserver la provenance et l'empreinte des poids avant tout remplacement.
  La voie AGPL du projet academique est detaillee dans
  [CONFORMITE_AGPL.md](CONFORMITE_AGPL.md) ; elle n'est pas encore achevee.
- Une detection reelle par webcam PC a produit une notification avec son sur
  le V20, confirmee par l'utilisateur le 11 octobre. La reconnexion apres
  refus TCP local a aussi ete testee, sans nouvelle alerte lors de ce test.
  L'utilisateur a choisi de ne pas refaire le pilote 24 h ; la disponibilite
  continue n'est donc pas demontree. La passerelle RTSP reste une recette
  materielle distincte.
