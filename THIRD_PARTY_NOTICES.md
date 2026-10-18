# Notices tierces

Le texte AGPL-3.0 dans LICENSE est propose pour le code applicatif de Sentinelle Maison, sous reserve de l'accord des auteurs mentionnes dans README.md. Les composants tiers gardent leurs licences respectives.

- YOLO11n ONNX, 320x320 : AGPL-3.0, export giangndm/yolo11-onnx, revision 18eac4f9d2911da4c519ada25f365ea1fd977cea ; SHA-256 ed25687f7f3176a041bcdd0173501629afcaaddf37711f2294ced377f249fd65. Source amont : https://github.com/ultralytics/ultralytics ; artefact : https://huggingface.co/giangndm/yolo11-onnx.
- ONNX Runtime Web 1.24.3 : MIT, voir licenses/ONNX-Runtime-MIT.txt et notices tierces associees. Source : https://github.com/microsoft/onnxruntime/tree/v1.24.3.
- YOLO11n Pose ONNX, 640x640 : AGPL-3.0, export Ultralytics 8.3.238, asset officiel https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-pose.onnx ; 11 853 451 octets ; SHA-256 93e2866b0ce678f99b4dd88af0c12e9ea2edf079a361dc2ecbc6226b77ff6408. Recette academique volontaire isolee uniquement ; poids conserves hors Git. Licence : https://www.ultralytics.com/license.
- TensorFlow.js 4.22.0 et COCO-SSD 2.2.3 : Apache-2.0, voir licenses/TensorFlow-*.txt. Sources https://github.com/tensorflow/tfjs et https://github.com/tensorflow/tfjs-models.
- Flutter, Material Icons, Cupertino Icons et composants de la PWA compilee : notices conservees dans static/mobile/assets/NOTICES ; sources Dart et verrou pubspec.lock inclus.
- Dependances Python : versions verrouillees dans requirements.txt ; leurs distributions amont ne sont pas relicenciees et ne sont pas incluses comme code applicatif.

Configuration : copier .env.example et tools/cloudflared-example.yml, puis renseigner localement les secrets. Les identites DPAPI, bases et captures ne font pas partie du code source. Aucun secret de production n'est necessaire pour reconstruire l'application.
