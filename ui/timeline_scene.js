/*
 * The Sacred Timeline — a cinematic composition.
 *
 * The spine is a luminous filament: it enters the frame low in the
 * foreground on the right, arcs gently across the center, and recedes
 * into fog on the upper left — continuing beyond what is visible.
 * Branches are not distributed evenly: a few primary gestures rise
 * clearly, secondary lines support them, distant whispers fade into
 * the void. Bloom stays a whisper. Labels are hover-only — the
 * composition must work before any text appears.
 *
 * Patterns adapted from three.js official examples (MIT):
 *   - shader point sprites (webgl_points_waves)
 *   - bloom composer (webgl_postprocessing_unreal_bloom)
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const VOID = 0x060913;
const FILAMENT = 0xf5eddc;   // white-hot core — the only near-white
const GOLD = 0xe3b36b;       // the sleeve around the core
const GOLD_SOFT = 0xd9a45b;
const BRANCH = 0x7c8ac4;     // restrained blue for branch timelines
const BRANCH_DEEP = 0x6e7fb8;
const PRUNED = 0xc9553a;

const container = document.getElementById('scene-root');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

let renderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
} catch (e) {
  document.getElementById('fallback').hidden = false;
  throw e;
}

renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
/* opaque canvas: a transparent WebGL iframe poisons Chromium compositing for
   anything painted above it (the scope dropdown rendered as a black card).
   The void vignette is drawn in-scene instead. */
renderer.setClearColor(0x060913, 1);
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(VOID, 0.012);      // far things sink slowly into the void

/* the deep-space vignette, painted inside the scene itself */
const vignette = (() => {
  const c = document.createElement('canvas');
  c.width = 32; c.height = 32;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(22, 12, 1, 16, 16, 24);
  grad.addColorStop(0, '#101735');
  grad.addColorStop(0.35, '#0a0f22');
  grad.addColorStop(0.72, '#060913');
  grad.addColorStop(1, '#03040a');
  g.fillStyle = grad;
  g.fillRect(0, 0, 32, 32);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const quad = new THREE.Mesh(
    new THREE.PlaneGeometry(2, 2),
    new THREE.MeshBasicMaterial({ map: tex, depthTest: false, depthWrite: false, fog: false }),
  );
  quad.frustumCulled = false;
  quad.renderOrder = -1;
  quad.onBeforeRender = () => {
    quad.position.setFromMatrixPosition(camera.matrixWorld);
    quad.quaternion.copy(camera.quaternion);
    quad.scale.set(1, 1, 1).multiplyScalar(camera.far * 0.9);
  };
  return quad;
})();
scene.add(vignette);

/* Camera: composed so the spine crosses the frame as a diagonal —
   near end enters low-right in the foreground (xmen/rami fork inside
   the frame, tips exiting the right edge intentionally), far end
   recedes upper-left into fog. No autorotate — the composition holds. */
const camera = new THREE.PerspectiveCamera(52, window.innerWidth / window.innerHeight, 0.1, 300);
camera.position.set(-4.5, 4.4, 22.0);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(-8.5, 2.0, -10.5);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.enablePan = false;
controls.minDistance = 9;
controls.maxDistance = 32;
controls.maxPolarAngle = Math.PI * 0.62;
controls.autoRotate = false;
controls.update();

/* ------------------------------------------------------------------ */
/* Soft round sprite texture — for fork lights and flow particles.     */
/* ------------------------------------------------------------------ */
function glowTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, 'rgba(255,255,255,1)');
  grad.addColorStop(0.35, 'rgba(255,255,255,0.35)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}
const GLOW = glowTexture();

/* ------------------------------------------------------------------ */
/* The Sacred Timeline — a filament entering the foreground and        */
/* receding into depth. Gentle organic wander, never a straight axis.  */
/* ------------------------------------------------------------------ */
const spineCurve = new THREE.CatmullRomCurve3([
  new THREE.Vector3(21.5, -3.2, 9.5),    // enters frame low-right, near
  new THREE.Vector3(13.5, -1.1, 5.8),
  new THREE.Vector3(6.0, 0.4, 2.6),
  new THREE.Vector3(-0.5, 0.9, -0.6),
  new THREE.Vector3(-7.5, 2.0, -5.0),
  new THREE.Vector3(-14.5, 2.7, -10.5),
  new THREE.Vector3(-22.5, 3.3, -17.0),  // sinks into fog, beyond the frame
]);

/* a layered luminous material: thin bright core inside a soft sleeve
   inside a barely-there atmosphere. Richness, not brightness.
   The tube tapers along the spine: thick where it enters the
   foreground, whisper-thin as it recedes into fog — depth you feel. */
function taperedTube(curve, radiusNear, radiusFar, color, opacity) {
  /* sample the curve; radius shrinks from near (world x>0) to far */
  const SEG = 96, RAD = 10;
  const frames = curve.computeFrenetFrames(SEG, false);
  const pts = curve.getSpacedPoints(SEG);
  const positions = [], normals = [], uvs = [], indices = [];
  const P = new THREE.Vector3(), N = new THREE.Vector3();
  for (let i = 0; i <= SEG; i++) {
    const t = i / SEG;
    const wx = pts[i].x;
    const k = THREE.MathUtils.clamp(wx / 21.5, 0, 1);              // 1 near, 0 far
    const r = radiusFar + (radiusNear - radiusFar) * k;
    const nrm = frames.normals[Math.min(i, SEG - 1)];
    const bin = frames.binormals[Math.min(i, SEG - 1)];
    for (let j = 0; j <= RAD; j++) {
      const v = (j / RAD) * Math.PI * 2;
      const sin = Math.sin(v), cos = Math.cos(v);
      N.copy(nrm).multiplyScalar(cos).addScaledVector(bin, sin).normalize();
      P.copy(pts[i]).addScaledVector(N, r);
      positions.push(P.x, P.y, P.z);
      normals.push(N.x, N.y, N.z);
      uvs.push(t, j / RAD);
    }
  }
  for (let i = 0; i < SEG; i++) {
    for (let j = 0; j < RAD; j++) {
      const a = i * (RAD + 1) + j, b = a + RAD + 1;
      indices.push(a, b, a + 1, b, b + 1, a + 1);
    }
  }
  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geom.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  geom.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geom.setIndex(indices);
  const mat = new THREE.MeshBasicMaterial({
    color, transparent: true, opacity,
    blending: THREE.AdditiveBlending, depthWrite: false, fog: true,
  });
  const mesh = new THREE.Mesh(geom, mat);
  mesh.userData.baseOpacity = opacity;
  return mesh;
}

/* the spine: warm off-white filament, gold sleeve, faint atmosphere */
const spineLayers = [
  taperedTube(spineCurve, 0.055, 0.022, FILAMENT, 0.95),
  taperedTube(spineCurve, 0.17, 0.07, GOLD, 0.18),
  taperedTube(spineCurve, 0.40, 0.16, GOLD_SOFT, 0.05),
];
for (const m of spineLayers) scene.add(m);

/* a sparse whisper of light travelling the spine */
const flowVert = `
  attribute float aOffset;
  uniform float uTime;
  varying float vFade;
  void main() {
    float t = fract(aOffset + uTime);
    vFade = smoothstep(0.0, 0.2, t) * (1.0 - smoothstep(0.75, 1.0, t));
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = (1.4 + vFade * 1.6) * (120.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;
const flowFrag = `
  uniform sampler2D uMap;
  uniform vec3 uColor;
  varying float vFade;
  void main() {
    vec4 tex = texture2D(uMap, gl_PointCoord);
    gl_FragColor = vec4(uColor * (0.5 + vFade), tex.a * vFade * 0.55);
  }
`;
function flowFor(curve, color, count, speed) {
  const lut = curve.getSpacedPoints(255);
  const positions = new Float32Array(count * 3);
  const offsets = new Float32Array(count);
  for (let i = 0; i < count; i++) offsets[i] = Math.random();
  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geom.setAttribute('aOffset', new THREE.BufferAttribute(offsets, 1));
  const mat = new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uColor: { value: new THREE.Color(color) },
      uMap: { value: GLOW },
    },
    vertexShader: flowVert,
    fragmentShader: flowFrag,
    transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
  });
  const points = new THREE.Points(geom, mat);
  points.userData = { speed, lut, count };
  return points;
}
function updateFlow(points, elapsed) {
  const { speed, lut, count } = points.userData;
  const pos = points.geometry.attributes.position.array;
  const offs = points.geometry.attributes.aOffset.array;
  for (let i = 0; i < count; i++) {
    const t = (offs[i] + elapsed * speed) % 1;
    const idx = Math.min(lut.length - 1, (t * lut.length) | 0);
    pos[i * 3] = lut[idx].x;
    pos[i * 3 + 1] = lut[idx].y;
    pos[i * 3 + 2] = lut[idx].z;
  }
  points.geometry.attributes.position.needsUpdate = true;
}
const spineFlow = flowFor(spineCurve, 0xffe9c4, 60, 0.008);
scene.add(spineFlow);

/* ------------------------------------------------------------------ */
/* Branch timelines — visual hierarchy, not an even distribution.       */
/*                                                                     */
/* PRIMARY: a few clear gestures (defenders, whatif — the deep         */
/* holdings). SECONDARY: supporting lines (fox x-men, ssu,            */
/* spider-verse). DISTANT: whispers that fade early (rami, webb,       */
/* fox:ff — the archive holds little or nothing of these).            */
/*                                                                     */
/* Fork t follows real chronology along the spine (2000 → 2021);       */
/* reach follows archive holdings. fox:ff is visible but not          */
/* searchable; the pruned stub is atmosphere.                          */
/* ------------------------------------------------------------------ */
const TIER = {
  primary:   { core: 0.036, coreOp: 0.80, sleeve: 0.100, sleeveOp: 0.13 },
  secondary: { core: 0.028, coreOp: 0.55, sleeve: 0.075, sleeveOp: 0.09 },
  distant:   { core: 0.019, coreOp: 0.32, sleeve: 0.050, sleeveOp: 0.05 },
};

const branchSpecs = [
  { key: 'fox:xmen',         label: 'FOX X-MEN',                     t: 0.13, len: 0.80, dir: [-0.15, 0.75, -0.35], color: BRANCH,      tier: 'secondary' },
  { key: 'sony:rami',        label: "TOBEY MAGUIRE'S SPIDER-MAN",    t: 0.21, len: 0.45, dir: [ 0.25, 0.55,  0.45], color: BRANCH_DEEP, tier: 'distant'   },
  { key: 'fox:ff',           label: 'FOX FANTASTIC FOUR',            t: 0.30, len: 0.42, dir: [-0.50, 0.45, -0.55], color: BRANCH_DEEP, tier: 'distant'   },
  { key: 'sony:webb',        label: 'THE AMAZING SPIDER-MAN',        t: 0.39, len: 0.40, dir: [ 0.30, 0.60,  0.25], color: BRANCH_DEEP, tier: 'distant'   },
  { key: 'defenders',        label: 'THE DEFENDERS',                 t: 0.50, len: 1.00, dir: [ 0.45, 0.85,  0.15], color: BRANCH,      tier: 'primary'   },
  { key: 'sony:ssu',         label: 'SSU — VENOM · MORBIUS · KRAVEN', t: 0.61, len: 0.62, dir: [ 0.70, 0.40,  0.20], color: BRANCH,      tier: 'secondary' },
  { key: 'sony:spiderverse', label: 'SPIDER-VERSE (ANIMATED)',       t: 0.70, len: 0.50, dir: [-0.55, 0.50, -0.40], color: BRANCH,      tier: 'secondary' },
  { key: 'whatif',           label: 'WHAT IF...?',                   t: 0.80, len: 0.85, dir: [-0.10, 0.95, -0.15], color: BRANCH,      tier: 'primary'   },
  { key: 'pruned',           label: 'A PRUNED BRANCH',               t: 0.90, len: 0.25, dir: [-0.40, -0.55, 0.30], color: PRUNED,      tier: 'distant', pruned: true },
];

const branches = [];
const forkLights = [];

for (const spec of branchSpecs) {
  const origin = spineCurve.getPointAt(spec.t);
  const d = new THREE.Vector3(...spec.dir).normalize();
  const reach = 10 * spec.len;
  const pts = [
    origin.clone(),
    origin.clone().addScaledVector(d, reach * 0.28).add(new THREE.Vector3(0, 0.5, 0)),
    origin.clone().addScaledVector(d, reach * 0.6).add(new THREE.Vector3(d.x * 1.2, 1.0, d.z * 1.2)),
    origin.clone().addScaledVector(d, reach * 0.85).add(new THREE.Vector3(d.x * 2.0, 1.4, d.z * 2.0)),
  ];
  const curve = new THREE.CatmullRomCurve3(pts);
  const tier = TIER[spec.tier];
  /* branches taper away from the spine: full tier radius at the fork,
     half at the tip — they thin as they leave the sacred timeline */
  const layers = [
    taperedTube(curve, tier.core, tier.core * 0.55, spec.color, spec.pruned ? 0.5 : tier.coreOp),
    taperedTube(curve, tier.sleeve, tier.sleeve * 0.55, spec.color, spec.pruned ? 0.10 : tier.sleeveOp),
  ];
  for (const m of layers) scene.add(m);

  /* screen-space pick LUT — sampled world points along the curve */
  const pickLUT = [];
  for (const p of curve.getSpacedPoints(24)) pickLUT.push(p.x, p.y, p.z);

  /* one small light at the fork — sized by the branch's importance */
  const lightScale = { primary: 0.9, secondary: 0.6, distant: 0.42 }[spec.tier];
  const light = new THREE.Sprite(new THREE.SpriteMaterial({
    map: GLOW, color: spec.pruned ? PRUNED : GOLD_SOFT,
    transparent: true, opacity: spec.pruned ? 0.35 : (spec.tier === 'primary' ? 0.55 : 0.42),
    blending: THREE.AdditiveBlending, depthWrite: false,
  }));
  light.position.copy(origin);
  light.scale.setScalar(spec.pruned ? 0.4 : lightScale);
  scene.add(light);

  const tip = curve.getPointAt(0.92);
  branches.push({ spec, layers, curve, tip, pickLUT, baseColor: new THREE.Color(spec.color), hover: 0, selected: false });
  forkLights.push({ light, spec });
}

/* the spine is pickable too — it is the MCU */
const spinePickLUT = [];
for (const p of spineCurve.getSpacedPoints(60)) spinePickLUT.push(p.x, p.y, p.z);

/* ------------------------------------------------------------------ */
/* Stars — a few, faint, twinkling.                                    */
/* ------------------------------------------------------------------ */
const starVert = `
  attribute float aScale;
  attribute float aPhase;
  attribute vec3 aColor;
  uniform float uTime;
  varying vec3 vColor;
  varying float vTwinkle;
  void main() {
    vColor = aColor;
    vTwinkle = 0.55 + 0.45 * sin(uTime * 0.7 + aPhase);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = aScale * (110.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;
const starFrag = `
  uniform sampler2D uMap;
  varying vec3 vColor;
  varying float vTwinkle;
  void main() {
    vec4 tex = texture2D(uMap, gl_PointCoord);
    gl_FragColor = vec4(vColor, tex.a * vTwinkle * 0.6);
  }
`;

const STARS = 400;
const starPos = new Float32Array(STARS * 3);
const starScale = new Float32Array(STARS);
const starPhase = new Float32Array(STARS);
const starColor = new Float32Array(STARS * 3);
const cBlue = new THREE.Color(0x8b93b5);
const cGold = new THREE.Color(0xd9a45b);
for (let i = 0; i < STARS; i++) {
  const r = 55 + Math.random() * 60;
  const th = Math.random() * Math.PI * 2;
  const ph = Math.acos(2 * Math.random() - 1);
  starPos[i * 3] = r * Math.sin(ph) * Math.cos(th) * 1.4;
  starPos[i * 3 + 1] = (Math.random() - 0.45) * 90;
  starPos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
  starScale[i] = 0.4 + Math.random() * 1.1;
  starPhase[i] = Math.random() * Math.PI * 2;
  const c = Math.random() < 0.14 ? cGold : cBlue;
  starColor[i * 3] = c.r; starColor[i * 3 + 1] = c.g; starColor[i * 3 + 2] = c.b;
}
const starGeom = new THREE.BufferGeometry();
starGeom.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
starGeom.setAttribute('aScale', new THREE.BufferAttribute(starScale, 1));
starGeom.setAttribute('aPhase', new THREE.BufferAttribute(starPhase, 1));
starGeom.setAttribute('aColor', new THREE.BufferAttribute(starColor, 3));
const starMat = new THREE.ShaderMaterial({
  uniforms: { uTime: { value: 0 }, uMap: { value: GLOW } },
  vertexShader: starVert,
  fragmentShader: starFrag,
  transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
});
const stars = new THREE.Points(starGeom, starMat);
scene.add(stars);

/* ------------------------------------------------------------------ */
/* Labels — invisible until the pointer approaches a branch; clicking   */
/* a branch selects that timeline for the search.                      */
/* ------------------------------------------------------------------ */
const labelSpecs = [
  { key: 'mcu', text: 'SACRED TIMELINE · MCU', anchor: () => spineCurve.getPointAt(0.52).add(new THREE.Vector3(0, -1.4, 0)) },
  ...branches.map((b) => ({ key: b.spec.key, text: b.spec.label, anchor: () => b.tip, pruned: !!b.spec.pruned })),
];

const labels = labelSpecs.map(({ key, text, pruned }) => {
  const el = document.createElement('div');
  el.className = 'scene-label' + (pruned ? ' pruned' : '') + (key === 'mcu' ? ' spine' : '');
  el.textContent = text;
  el.dataset.key = key;
  container.appendChild(el);
  return { key, el, pruned, screen: null, reveal: 0, selected: false };
});

const pointer = { x: -1e4, y: -1e4 };

const LABEL_REVEAL_R = 130;   // px — proximity that reveals a label
const v = new THREE.Vector3();

function updateLabels() {
  for (const l of labels) {
    const branch = branches.find((b) => b.spec.key === l.key);
    const pos = l.key === 'mcu'
      ? labelSpecs[0].anchor()
      : branch.tip;
    v.copy(pos).project(camera);
    const behind = v.z > 1;
    const x = (v.x * 0.5 + 0.5) * window.innerWidth;
    const y = (-v.y * 0.5 + 0.5) * window.innerHeight;
    l.screen = behind ? null : { x, y };
    const near = !behind && pointer.x > -9999 &&
      Math.hypot(pointer.x - x, pointer.y - y) < LABEL_REVEAL_R;
    l.reveal += ((near || l.selected) && !behind ? 1 : -1) * 0.12;
    l.reveal = THREE.MathUtils.clamp(l.reveal, 0, 1);
    const dist = camera.position.distanceTo(pos);
    const depthFade = THREE.MathUtils.clamp(1 - (dist - 14) / 60, 0.2, 0.9);
    l.el.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px)`;
    l.el.style.opacity = behind ? '0' : String(l.reveal * depthFade);
  }
}

/* --- picking: screen-space proximity against each curve — forgiving   */
/* for thin filaments. Hover reveals, click selects.                      */
const PICK_R = 26;                       // px — how close the pointer must be
let hoverKey = null;
let selectedKey = null;
const pickV = new THREE.Vector3();

function pickAt(px, py) {
  let best = null, bestD = PICK_R;
  // branches first (they're the intent), then the spine
  for (const b of branches) {
    for (let i = 0; i < b.pickLUT.length; i += 3) {
      pickV.set(b.pickLUT[i], b.pickLUT[i + 1], b.pickLUT[i + 2]).project(camera);
      if (pickV.z > 1) break;
      const x = (pickV.x * 0.5 + 0.5) * window.innerWidth;
      const y = (-pickV.y * 0.5 + 0.5) * window.innerHeight;
      const d = Math.hypot(px - x, py - y);
      if (d < bestD) { bestD = d; best = b.spec.key; }
    }
  }
  if (best) return best;
  for (let i = 0; i < spinePickLUT.length; i += 3) {
    pickV.set(spinePickLUT[i], spinePickLUT[i + 1], spinePickLUT[i + 2]).project(camera);
    if (pickV.z > 1) break;
    const x = (pickV.x * 0.5 + 0.5) * window.innerWidth;
    const y = (-pickV.y * 0.5 + 0.5) * window.innerHeight;
    if (Math.hypot(px - x, py - y) < PICK_R) return 'mcu';
  }
  return null;
}

container.addEventListener('pointermove', (e) => {
  const r = renderer.domElement.getBoundingClientRect();
  pointer.x = e.clientX - r.left;
  pointer.y = e.clientY - r.top;
  hoverKey = pickAt(pointer.x, pointer.y);
  const clickable = hoverKey && hoverKey !== 'pruned';
  container.style.cursor = clickable ? 'pointer' : '';
});
container.addEventListener('pointerleave', () => {
  pointer.x = -1e4; pointer.y = -1e4; hoverKey = null;
});
container.addEventListener('click', () => {
  if (!hoverKey || hoverKey === 'pruned') return;       // pruned lines can't be searched
  selectedKey = selectedKey === hoverKey ? null : hoverKey;   // second click clears
  for (const l of labels) {
    l.selected = l.key === selectedKey;
    l.el.classList.toggle('selected', l.selected);
  }
  parent.postMessage({ type: 'timeline-select', timeline: selectedKey }, '*');
});

/* ------------------------------------------------------------------ */
/* Highlight bridge — evidence rows warm a branch toward gold.          */
/* ------------------------------------------------------------------ */
let highlighted = null;
const GOLD_HL = new THREE.Color(0xd9a45b);
window.addEventListener('message', (e) => {
  const d = e.data;
  if (d && d.type === 'highlight' && (typeof d.branch === 'string' || d.branch === null)) highlighted = d.branch || null;
});

/* debug/verification hook */
window.__sceneState = () => ({
  highlighted,
  selected: selectedKey,
  hover: hoverKey,
  branchColors: Object.fromEntries(branches.map((b) => [b.spec.key, b.layers[0].material.color.getHexString()])),
});

/* ------------------------------------------------------------------ */
/* Postprocessing — bloom as a whisper.                               */
/* ------------------------------------------------------------------ */
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(window.innerWidth, window.innerHeight), 0.4, 0.5, 0.32);
composer.addPass(bloom);
composer.addPass(new OutputPass());

/* ------------------------------------------------------------------ */
/* Fade the canvas in, once, gently.                                   */
/* ------------------------------------------------------------------ */
requestAnimationFrame(() => container.classList.add('live'));

/* ------------------------------------------------------------------ */
/* Resize / visibility / loop.                                         */
/* ------------------------------------------------------------------ */
window.addEventListener('resize', onResize);
function onResize() {
  const w = window.innerWidth, h = window.innerHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  composer.setSize(w, h);
}

const clock = new THREE.Clock();
let elapsed = 0;

renderer.setAnimationLoop(tick);

function tick() {
  const dt = Math.min(clock.getDelta(), 0.05);
  elapsed += dt;

  spineFlow.material.uniforms.uTime.value = reducedMotion ? 0 : elapsed * spineFlow.userData.speed;
  updateFlow(spineFlow, reducedMotion ? 0 : elapsed);
  starMat.uniforms.uTime.value = reducedMotion ? 0 : elapsed;

  /* fork lights breathe, barely */
  for (const { light } of forkLights) {
    const base = light.material.userData.baseOpacity ?? (light.material.userData.baseOpacity = light.material.opacity);
    light.material.opacity = reducedMotion ? base : base * (0.85 + Math.sin(elapsed * 0.8 + light.position.x) * 0.15);
  }

  /* branch state: selected holds gold, hovered brightens, evidence highlight warms */
  for (const b of branches) {
    const isSel = selectedKey === b.spec.key;
    const isHover = hoverKey === b.spec.key;
    const isHi = highlighted === b.spec.key;
    b.hover += ((isHover || isSel || isHi) ? 1 : -1) * 0.1;
    b.hover = THREE.MathUtils.clamp(b.hover, 0, 1);
    const target = isSel || isHi ? GOLD_HL : b.baseColor;
    for (const m of b.layers) {
      m.material.color.lerp(target, isSel || isHi ? 0.08 : 0.05);
      m.material.opacity = m.userData.baseOpacity * (1 + b.hover * 0.6);
    }
  }

  /* the spine dims slightly when another timeline is selected */
  const spineF = selectedKey && selectedKey !== 'mcu' && highlighted !== 'mcu' ? 0.55 : 1;
  for (const m of spineLayers) m.material.opacity = m.userData.baseOpacity * spineF;

  controls.update();
  if (!window.__framed) updateLabels();
  composer.render();
}

/* pause rendering when the tab is hidden (iframe embeds) */
document.addEventListener('visibilitychange', () => {
  renderer.setAnimationLoop(document.hidden ? null : tick);
  if (!document.hidden) clock.getDelta();
});

/* composition hook for art-direction verification: where does everything
   land on screen? (px, y-down, viewport-relative) */
window.__compose = () => {
  const project = (p) => {
    v.copy(p).project(camera);
    return { x: (v.x * 0.5 + 0.5) * window.innerWidth, y: (-v.y * 0.5 + 0.5) * window.innerHeight, z: v.z };
  };
  const spine = spineCurve.getSpacedPoints(48).map(project);
  const branchBoxes = branches.map((b) => {
    const pts = curveScreen(b);
    return {
      key: b.spec.key,
      min: { x: Math.min(...pts.map((p) => p.x)), y: Math.min(...pts.map((p) => p.y)) },
      max: { x: Math.max(...pts.map((p) => p.x)), y: Math.max(...pts.map((p) => p.y)) },
    };
  });
  function curveScreen(b) {
    return b.curve.getSpacedPoints(16).map(project);
  }
  return {
    viewport: { w: window.innerWidth, h: window.innerHeight },
    spine,
    branchBoxes,
  };
};

/* live art-direction hook: camera + controls, for calibration */
window.__cam = { camera, controls, spineCurve: () => spineCurve };

/* probe hook for art-direction verification: luminance grid + structure.
   render() right before readPixels keeps the buffer readable without
   preserveDrawingBuffer (which caused iframe-overlay compositing bugs). */
window.__probe = () => {
  composer.render();
  const gl = renderer.getContext();
  const W = gl.drawingBufferWidth, H = gl.drawingBufferHeight;
  const px = new Uint8Array(W * H * 4);
  gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, px);
  // 24x10 luminance grid, plus global overexposure stats
  const GX = 24, GY = 10;
  const grid = [];
  for (let gy = 0; gy < GY; gy++) {
    const row = [];
    for (let gx = 0; gx < GX; gx++) {
      let sum = 0, n = 0, hot = 0;
      for (let y = Math.floor(gy * H / GY); y < Math.floor((gy + 1) * H / GY); y += 4) {
        for (let x = Math.floor(gx * W / GX); x < Math.floor((gx + 1) * W / GX); x += 4) {
          const i = (y * W + x) * 4;
          const lum = (0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]) / 255;
          sum += lum; n++;
          if (lum > 0.92) hot++;
        }
      }
      row.push(n ? { lum: sum / n, hot: hot / n } : { lum: 0, hot: 0 });
    }
    grid.push(row);
  }
  let total = 0, hotTotal = 0;
  for (let i = 0; i < W * H * 4; i += 4) {
    const lum = (0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]) / 255;
    total++;
    if (lum > 0.92) hotTotal++;
  }
  // structure: bright-column coverage (does a readable structure span the frame?)
  const colBright = new Array(GX).fill(false);
  for (let gx = 0; gx < GX; gx++) {
    let hits = 0;
    for (let gy = 0; gy < GY; gy++) {
      if (grid[gy][gx].lum > 0.18) hits++;
    }
    colBright[gx] = hits >= 1;
  }
  let runs = [], run = 0;
  for (let i = 0; i < GX; i++) {
    if (colBright[i]) { run++; } else if (run) { runs.push(run); run = 0; }
  }
  if (run) runs.push(run);
  return {
    drawnPixels: total,
    overexposedFrac: total ? hotTotal / total : 0,
    longestBrightRun: Math.max(...runs, 0) + '/' + GX,
    grid: grid.map(r => r.map(c => (c.lum > 0.55 ? '#' : c.lum > 0.30 ? '+' : c.lum > 0.12 ? '.' : ' ')).join('')).join('\n'),
  };
};
