import { BrowserMultiFormatReader } from '@zxing/browser';
import { BarcodeFormat, DecodeHintType } from '@zxing/library';
import { digitsOf } from './evaluator';

// Built-in 1D EAN-13 / UPC-A decoder fallback for crisp barcode images when native/ZXing miss
const L_PAT = [
  [3, 2, 1, 1], [2, 2, 2, 1], [2, 1, 2, 2], [1, 4, 1, 1], [1, 1, 3, 2],
  [1, 2, 3, 1], [1, 1, 1, 4], [1, 3, 1, 2], [1, 2, 1, 3], [3, 1, 1, 2],
];
const G_PAT = L_PAT.map((p) => [...p].reverse());
const PARITY = [
  'LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG',
  'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL',
];

function matchDigit(r: number[], mod: number, left: boolean) {
  let best = { d: -1, p: '', err: 99 };
  const test = (pats: number[][], tag: string) => {
    for (let d = 0; d < 10; d++) {
      let e = 0;
      for (let i = 0; i < 4; i++) e += Math.abs(r[i] / mod - pats[d][i]);
      if (e < best.err) best = { d, p: tag, err: e };
    }
  };
  if (left) {
    test(L_PAT, 'L');
    test(G_PAT, 'G');
  } else {
    test(L_PAT, 'R');
  }
  return best.err < 1.35 ? best : null;
}

function checksumOK(ds: number[]): boolean {
  const s = ds.slice(0, 12).reduce((a, d, i) => a + d * (i % 2 ? 3 : 1), 0);
  return (10 - (s % 10)) % 10 === ds[12];
}

function decodeRuns(lens: number[], cols: number[]): string | null {
  for (let i = 0; i + 59 <= lens.length; i++) {
    if (cols[i] !== 1) continue;
    const mod = (lens[i] + lens[i + 1] + lens[i + 2]) / 3;
    if (mod < 0.8) continue;
    if (
      Math.abs(lens[i] / mod - 1) > 0.65 ||
      Math.abs(lens[i + 1] / mod - 1) > 0.65 ||
      Math.abs(lens[i + 2] / mod - 1) > 0.65
    ) {
      continue;
    }
    const mg = i + 27;
    const eg = i + 56;
    if (eg + 2 >= lens.length) continue;
    const mAvg = (lens[mg] + lens[mg + 1] + lens[mg + 2] + lens[mg + 3] + lens[mg + 4]) / 5;
    if (Math.abs(mAvg / mod - 1) > 0.55) continue;
    if (Math.abs((lens[eg] + lens[eg + 1] + lens[eg + 2]) / 3 / mod - 1) > 0.55) continue;

    const ld: number[] = [];
    let par = '';
    let ok = true;
    for (let k = 0; k < 6; k++) {
      const m = matchDigit(lens.slice(i + 3 + k * 4, i + 7 + k * 4), mod, true);
      if (!m) { ok = false; break; }
      ld.push(m.d);
      par += m.p;
    }
    if (!ok) continue;
    const first = PARITY.indexOf(par);
    if (first < 0) continue;

    const rd: number[] = [];
    for (let k = 0; k < 6; k++) {
      const m = matchDigit(lens.slice(mg + 5 + k * 4, mg + 9 + k * 4), mod, false);
      if (!m) { ok = false; break; }
      rd.push(m.d);
    }
    if (!ok) continue;
    const all = [first, ...ld, ...rd];
    if (checksumOK(all)) return all.join('');
  }
  return null;
}

function decodeLine(line: Float32Array): string | null {
  const n = line.length;
  const sm = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    sm[i] = (line[Math.max(0, i - 1)] + line[i] * 2 + line[Math.min(n - 1, i + 1)]) / 4;
  }
  const win = Math.max(16, Math.floor(n / 10));
  const pre = new Float64Array(n + 1);
  for (let i = 0; i < n; i++) pre[i + 1] = pre[i] + sm[i];

  for (const bias of [0.95, 1.0, 1.05]) {
    const lens: number[] = [];
    const cols: number[] = [];
    let cur = -1;
    let run = 0;
    for (let i = 0; i < n; i++) {
      const a = Math.max(0, i - win);
      const b = Math.min(n, i + win);
      const mean = (pre[b] - pre[a]) / (b - a);
      const c = sm[i] < mean * bias ? 1 : 0;
      if (c === cur) run++;
      else {
        if (cur >= 0) { lens.push(run); cols.push(cur); }
        cur = c;
        run = 1;
      }
    }
    if (cur >= 0) { lens.push(run); cols.push(cur); }
    const hit =
      decodeRuns(lens, cols) ||
      decodeRuns([...lens].reverse(), [...cols].reverse());
    if (hit) return hit;
  }
  return null;
}

function decodeCanvas1D(cv: HTMLCanvasElement): string | null {
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  if (!ctx) return null;
  const { width: w, height: h } = cv;
  const img = ctx.getImageData(0, 0, w, h).data;
  const rows = [0.5, 0.42, 0.58, 0.34, 0.66, 0.25, 0.75, 0.18, 0.82];
  const votes = new Map<string, number>();
  for (const frac of rows) {
    const y = Math.floor(h * frac);
    const line = new Float32Array(w);
    for (let x = 0; x < w; x++) {
      const o = (y * w + x) * 4;
      line[x] = img[o] * 0.299 + img[o + 1] * 0.587 + img[o + 2] * 0.114;
    }
    const code = decodeLine(line);
    if (code) {
      votes.set(code, (votes.get(code) || 0) + 1);
      if ((votes.get(code) || 0) >= 2) return code;
    }
  }
  return votes.size ? [...votes.entries()].sort((a, b) => b[1] - a[1])[0][0] : null;
}

function makeZxingReader(): BrowserMultiFormatReader {
  const hints = new Map();
  hints.set(DecodeHintType.POSSIBLE_FORMATS, [
    BarcodeFormat.UPC_A,
    BarcodeFormat.UPC_E,
    BarcodeFormat.EAN_13,
    BarcodeFormat.EAN_8,
    BarcodeFormat.CODE_128,
  ]);
  hints.set(DecodeHintType.TRY_HARDER, true);
  return new BrowserMultiFormatReader(hints, {
    delayBetweenScanAttempts: 180,
    delayBetweenScanSuccess: 1200,
  });
}

export interface CameraController {
  stop: () => void;
}

export async function startCameraBarcodeScan(
  videoEl: HTMLVideoElement,
  onCode: (code: string) => void,
  onError: (message: string) => void
): Promise<CameraController> {
  if (!navigator.mediaDevices?.getUserMedia) {
    onError(
      'Camera access is unavailable here. Use "Use a barcode photo" below, or open this app over HTTPS on your phone.'
    );
    return { stop: () => undefined };
  }

  let stopped = false;
  let controls: { stop: () => void } | null = null;
  const reader = makeZxingReader();

  try {
    controls = await reader.decodeFromConstraints(
      {
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      },
      videoEl,
      (result) => {
        if (stopped || !result) return;
        const digits = digitsOf(result.getText());
        if (digits.length >= 8) {
          stopped = true;
          controls?.stop();
          onCode(digits);
        }
      }
    );
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    onError(
      /permission|denied|notallowed/i.test(msg)
        ? 'Camera permission was blocked. Allow camera access or tap "Use a barcode photo" instead.'
        : 'Could not start the camera here. Tap "Use a barcode photo" to pick or snap a barcode picture.'
    );
  }

  return {
    stop: () => {
      stopped = true;
      try {
        controls?.stop();
      } catch {
        // ignore stop errors
      }
      const stream = videoEl.srcObject as MediaStream | null;
      stream?.getTracks().forEach((t) => t.stop());
      videoEl.srcObject = null;
    },
  };
}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = (e) => {
      URL.revokeObjectURL(url);
      reject(e);
    };
    img.src = url;
  });
}

function scaledCanvas(img: HTMLImageElement, maxDim: number, rotate90 = false): HTMLCanvasElement {
  const s = Math.min(1, maxDim / Math.max(img.naturalWidth || 1, img.naturalHeight || 1));
  const w = Math.max(1, Math.round((img.naturalWidth || 1) * s));
  const h = Math.max(1, Math.round((img.naturalHeight || 1) * s));
  const cv = document.createElement('canvas');
  cv.width = rotate90 ? h : w;
  cv.height = rotate90 ? w : h;
  const ctx = cv.getContext('2d');
  if (ctx) {
    if (rotate90) {
      ctx.translate(cv.width / 2, cv.height / 2);
      ctx.rotate(Math.PI / 2);
      ctx.drawImage(img, -w / 2, -h / 2, w, h);
    } else {
      ctx.drawImage(img, 0, 0, w, h);
    }
  }
  return cv;
}

export async function decodeBarcodeFromPhoto(file: File): Promise<string | null> {
  const img = await loadImage(file);
  const cv = scaledCanvas(img, 1400, false);

  // 1. Native BarcodeDetector (Chrome/Edge/Android)
  const BD = (window as unknown as { BarcodeDetector?: new (o: { formats: string[] }) => { detect: (src: HTMLCanvasElement) => Promise<Array<{ rawValue: string }>> } }).BarcodeDetector;
  if (BD) {
    try {
      const det = new BD({ formats: ['upc_a', 'upc_e', 'ean_13', 'ean_8', 'code_128'] });
      const hits = await det.detect(cv);
      if (hits?.[0]?.rawValue) {
        const d = digitsOf(hits[0].rawValue);
        if (d.length >= 8) return d;
      }
    } catch {
      // fall through
    }
  }

  // 2. ZXing multi-format decoder (works on iOS Safari & all browsers)
  const reader = makeZxingReader();
  try {
    const res = reader.decodeFromCanvas(cv);
    const d = digitsOf(res.getText());
    if (d.length >= 8) return d;
  } catch {
    // try rotated 90 degrees in case user held phone vertically over a sideways barcode
    try {
      const rot = scaledCanvas(img, 1400, true);
      const res = reader.decodeFromCanvas(rot);
      const d = digitsOf(res.getText());
      if (d.length >= 8) return d;
    } catch {
      // fall through to 1D scanline decoder
    }
  }

  // 3. Built-in 1D EAN-13/UPC-A scanline fallback
  const d1 = decodeCanvas1D(cv);
  if (d1) return d1;
  return decodeCanvas1D(scaledCanvas(img, 1400, true));
}
