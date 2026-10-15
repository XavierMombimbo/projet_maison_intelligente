# YOLO browser assets

- Model: YOLO11n detection, ONNX export, 320 x 320 input
- Source: `giangndm/yolo11-onnx` on Hugging Face, revision `18eac4f9d2911da4c519ada25f365ea1fd977cea`
- Model SHA-256: `ed25687f7f3176a041bcdd0173501629afcaaddf37711f2294ced377f249fd65`
- Model license: AGPL-3.0
- Runtime: ONNX Runtime Web 1.24.3

The model and runtime are served locally by Django/WhiteNoise so browser inference does not send video frames to a third-party inference service.
