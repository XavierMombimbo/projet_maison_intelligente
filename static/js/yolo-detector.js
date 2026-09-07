(() => {
  "use strict";

  const MODEL_SIZE = 640;
  const PERSON_CLASS = 0;

  const iou = (a, b) => {
    const x1 = Math.max(a[0], b[0]);
    const y1 = Math.max(a[1], b[1]);
    const x2 = Math.min(a[0] + a[2], b[0] + b[2]);
    const y2 = Math.min(a[1] + a[3], b[1] + b[3]);
    const intersection = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
    return intersection / (a[2] * a[3] + b[2] * b[3] - intersection || 1);
  };

  class YoloDetector {
    constructor(session) { this.session = session; }

    static async create({modelUrl, wasmUrl}) {
      if (!window.ort?.InferenceSession) throw new Error("Le runtime YOLO n’est pas chargé.");
      // The UMD WASM build already embeds its JavaScript glue. Overriding only
      // the binary keeps that embedded module in use and avoids a second
      // dynamic request for ort-wasm-simd-threaded.mjs.
      window.ort.env.wasm.wasmPaths = {wasm: new URL(wasmUrl, window.location.origin).toString()};
      window.ort.env.wasm.numThreads = 1;
      window.ort.env.wasm.proxy = true;
      window.ort.env.wasm.simd = true;
      const session = await window.ort.InferenceSession.create(modelUrl, {
        executionProviders: ["wasm"],
        graphOptimizationLevel: "all"
      });
      return new YoloDetector(session);
    }

    async detect(video) {
      const width = video.videoWidth || 640;
      const height = video.videoHeight || 360;
      const scale = Math.min(MODEL_SIZE / width, MODEL_SIZE / height);
      const resizedWidth = Math.round(width * scale);
      const resizedHeight = Math.round(height * scale);
      const offsetX = (MODEL_SIZE - resizedWidth) / 2;
      const offsetY = (MODEL_SIZE - resizedHeight) / 2;
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = MODEL_SIZE;
      const ctx = canvas.getContext("2d", {willReadFrequently: true});
      ctx.fillStyle = "#808080";
      ctx.fillRect(0, 0, MODEL_SIZE, MODEL_SIZE);
      ctx.drawImage(video, offsetX, offsetY, resizedWidth, resizedHeight);
      const pixels = ctx.getImageData(0, 0, MODEL_SIZE, MODEL_SIZE).data;
      const input = new Float32Array(3 * MODEL_SIZE * MODEL_SIZE);
      const plane = MODEL_SIZE * MODEL_SIZE;
      for (let i = 0; i < plane; i++) {
        input[i] = pixels[i * 4] / 255;
        input[plane + i] = pixels[i * 4 + 1] / 255;
        input[plane * 2 + i] = pixels[i * 4 + 2] / 255;
      }
      const inputName = this.session.inputNames[0];
      const output = await this.session.run({[inputName]: new window.ort.Tensor("float32", input, [1, 3, MODEL_SIZE, MODEL_SIZE])});
      const tensor = output[this.session.outputNames[0]];
      const data = tensor.data;
      const channelsFirst = tensor.dims[1] === 84;
      const count = channelsFirst ? tensor.dims[2] : tensor.dims[1];
      const score = (channel, index) => channelsFirst ? data[channel * count + index] : data[index * 84 + channel];
      const candidates = [];
      for (let i = 0; i < count; i++) {
        const confidence = score(4 + PERSON_CLASS, i);
        if (confidence < 0.35) continue;
        const cx = score(0, i), cy = score(1, i), boxWidth = score(2, i), boxHeight = score(3, i);
        const x = Math.max(0, (cx - boxWidth / 2 - offsetX) / scale);
        const y = Math.max(0, (cy - boxHeight / 2 - offsetY) / scale);
        candidates.push({bbox: [x, y, Math.min(boxWidth / scale, width - x), Math.min(boxHeight / scale, height - y)], class: "person", score: confidence});
      }
      candidates.sort((a, b) => b.score - a.score);
      const kept = [];
      for (const candidate of candidates) {
        if (!kept.some(item => iou(item.bbox, candidate.bbox) > 0.45)) kept.push(candidate);
        if (kept.length >= 20) break;
      }
      return kept;
    }
  }

  window.YoloDetector = YoloDetector;
})();
