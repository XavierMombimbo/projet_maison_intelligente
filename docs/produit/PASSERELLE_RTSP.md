# Passerelle RTSP locale

La passerelle CAM-002 tourne sur un ordinateur du même réseau que la caméra. Elle récupère uniquement la configuration de la caméra associée à son identité, ouvre le flux avec des délais bornés et envoie un signal de présence au serveur. Les erreurs n’affichent jamais l’URL authentifiée.

## Installation Windows

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gateway.txt
```

Dans l’application, créer une caméra RTSP puis générer son code d’appairage. Dans le terminal de la passerelle :

```powershell
.\.venv\Scripts\python.exe -m gateway pair --server http://127.0.0.1:8001
.\.venv\Scripts\python.exe -m gateway run --once
```

Le code est demandé sans être affiché. Sous Windows, l’identité durable et la clé de signature sont chiffrées par DPAPI pour l’utilisateur courant dans `%LOCALAPPDATA%\SentinelleMaison\gateway.credentials`. Le mot de passe RTSP reste chiffré dans la base et n’est transmis qu’à cette identité par HTTPS ; `http://` est accepté uniquement pour localhost.

Le test `--once` réussit seulement après réception d’une vraie image H.264. Il affiche l’adresse expurgée, la résolution et le codec. Il ne crée aucun faux flux.

## Service continu et reconnexion

```powershell
.\.venv\Scripts\python.exe -m gateway run
```

- ouverture RTSP : 8 secondes maximum ;
- lecture d’image : 5 secondes maximum ;
- reconnexion exponentielle de 1 à 30 secondes avec légère dispersion ;
- retour à une seconde après une image valide ;
- signal de présence toutes les 30 secondes ;
- aucune connexion quand la surveillance est désactivée ;
- arrêt immédiat avec `Ctrl+C`.

Après un test réel réussi, installer le lancement automatique à l’ouverture de session :

```powershell
powershell -ExecutionPolicy Bypass -File .\gateway\install_windows_startup.ps1
```

Le Planificateur de tâches redémarre le processus après un échec. Pour le retirer :

```powershell
powershell -ExecutionPolicy Bypass -File .\gateway\uninstall_windows_startup.ps1
```

## Recette matérielle CAM-002

1. Utiliser un compte RTSP de lecture dédié et un flux H.264.
2. Lancer `run --once` et consigner modèle, firmware, résolution et codec.
3. Lancer le service continu, débrancher la caméra et vérifier que le délai monte sans boucle rapide.
4. Rebrancher la caméra et mesurer le temps jusqu’au retour du signal de présence.
5. Vérifier que le terminal, Trello et les journaux ne contiennent ni utilisateur, ni mot de passe, ni URL authentifiée.

La carte ne peut être terminée qu’après cette recette sur une caméra physique.

