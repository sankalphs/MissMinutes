/*
 * The Sacred Timeline — a cinematic composition.
 *
 * One white-gold filament travels diagonally into depth; branches diverge
 * quietly upward; a few stars and fork lights, nothing else. Bloom is a
 * whisper, not a searchlight. Labels are small, unboxed, depth-faded.
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
renderer.setClearColor(0x000000, 0);           // the page vignette shows through
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(VOID, 0.02);      // far things sink into the void

/* Camera: slightly above, off-axis — the spine reads as a diagonal. */
const camera = new THREE.PerspectiveCamera(42, window.innerWidth / window.innerHeight, 0.1, 300);
camera.position.set(-7.5, 4.6, 15.5);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(1.5, 0.4, -2.5);
controls.enableDamping = true;
controls.dampingFactor = 0.05;
controls.enablePan = false;
controls.minDistance = 9;
controls.maxDistance = 32;
controls.maxPolarAngle = Math.PI * 0.58;
controls.autoRotate = !reducedMotion;
controls.autoRotateSpeed = 0.08;               // near-imperceptible drift
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
/* The Sacred Timeline — a horizontal filament receding into depth.    */
/* ------------------------------------------------------------------ */
const spineCurve = new THREE.CatmullRomCurve3([
  new THREE.Vector3(-28, 2.4, 13),
  new THREE.Vector3(-13, 1.3, 6),
  new THREE.Vector3(-2, 0.6, 0),
  new THREE.Vector3(9, -0.2, -7),
  new THREE.Vector3(21, -1.3, -14),
  new THREE.Vector3(30, -2.1, -19),
]);

function tubeFor(curve, color, radius, opacity) {
  const geom = new THREE.TubeGeometry(curve, 80, radius, 8, false);
  const mat = new THREE.MeshBasicMaterial({
    color, transparent: true, opacity,
    blending: THREE.AdditiveBlending, depthWrite: false, fog: true,
  });
  return new THREE.Mesh(geom, mat);
}

/* dual tube: bright thin core inside a soft gold sleeve */
const spineCore = tubeFor(spineCurve, FILAMENT, 0.022, 0.95);
const spineSleeve = tubeFor(spineCurve, GOLD, 0.085, 0.16);
scene.add(spineSleeve, spineCore);

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
/* Branch timelines — they diverge upward, into depth, and quiet down. */
/* ------------------------------------------------------------------ */
const branchSpecs = [
  { key: 'whatif', name: 'WHAT IF...?', t: 0.30, color: BRANCH, len: 1.0, dir: [-0.55, 1, 0.25] },
  { key: 'fox', name: 'FOX', t: 0.43, color: BRANCH, len: 0.9, dir: [0.5, 1, -0.55] },
  { key: 'sony', name: 'SONY', t: 0.56, color: BRANCH_DEEP, len: 0.75, dir: [-0.4, 1, -0.5] },
  { key: 'defenders', name: 'DEFENDERS', t: 0.68, color: BRANCH_DEEP, len: 0.6, dir: [0.45, 1, 0.35] },
  { key: 'pruned', name: 'PRUNED', t: 0.82, color: PRUNED, len: 0.28, dir: [0.2, -0.5, 0.15], pruned: true },
];

const branches = [];
const forkLights = [];
const labelAnchors = [];

for (const spec of branchSpecs) {
  const origin = spineCurve.getPointAt(spec.t);
  const d = new THREE.Vector3(...spec.dir).normalize();
  const reach = 10 * spec.len;
  const pts = [
    origin.clone(),
    origin.clone().addScaledVector(d, reach * 0.28).add(new THREE.Vector3(0, 0.6, 0)),
    origin.clone().addScaledVector(d, reach * 0.6).add(new THREE.Vector3(d.x * 1.4, 1.2, d.z * 1.4)),
    origin.clone().addScaledVector(d, reach * 0.85).add(new THREE.Vector3(d.x * 2.4, 1.6, d.z * 2.4)),
  ];
  const curve = new THREE.CatmullRomCurve3(pts);
  const tube = tubeFor(curve, spec.color, spec.pruned ? 0.018 : 0.032, spec.pruned ? 0.5 : 0.55);
  scene.add(tube);

  /* one small light at the fork — a temporal junction, nothing more */
  const light = new THREE.Sprite(new THREE.SpriteMaterial({
    map: GLOW, color: spec.pruned ? PRUNED : GOLD_SOFT,
    transparent: true, opacity: spec.pruned ? 0.35 : 0.5,
    blending: THREE.AdditiveBlending, depthWrite: false,
  }));
  light.position.copy(origin);
  light.scale.setScalar(spec.pruned ? 0.4 : 0.65);
  scene.add(light);

  const tip = curve.getPointAt(0.92);
  labelAnchors.push({ name: spec.name, pos: tip, pruned: !!spec.pruned });
  branches.push({ spec, tube, curve, baseColor: new THREE.Color(spec.color) });
  forkLights.push({ light, spec });
}

/* the spine gets its own label */
labelAnchors.push({ name: 'SACRED TIMELINE · MCU', pos: spineCurve.getPointAt(0.5).add(new THREE.Vector3(0, -1.1, 0)), spine: true });

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
/* Labels — small, unboxed, depth-faded, culled behind the camera.     */
/* ------------------------------------------------------------------ */
const labels = labelAnchors.map(({ name, pos, pruned, spine }) => {
  const el = document.createElement('div');
  el.className = 'scene-label' + (pruned ? ' pruned' : '') + (spine ? ' spine' : '');
  el.textContent = name;
  container.appendChild(el);
  return { el, pos: pos.clone(), pruned, spine };
});

const v = new THREE.Vector3();
function updateLabels() {
  for (const l of labels) {
    v.copy(l.pos).project(camera);
    const behind = v.z > 1;
    const x = (v.x * 0.5 + 0.5) * window.innerWidth;
    const y = (-v.y * 0.5 + 0.5) * window.innerHeight;
    const offscreen = x < -60 || x > window.innerWidth + 60 || y < -20 || y > window.innerHeight + 20;
    const dist = camera.position.distanceTo(l.pos);
    const depthFade = THREE.MathUtils.clamp(1 - (dist - 14) / 52, 0.15, 0.85);
    l.el.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px)`;
    l.el.style.opacity = behind || offscreen ? '0' : String(depthFade);
  }
}

/* ------------------------------------------------------------------ */
/* Highlight bridge — evidence rows warm a branch toward gold (SP3).   */
/* ------------------------------------------------------------------ */
let highlighted = null;
const GOLD_HL = new THREE.Color(0xd9a45b);
window.addEventListener('message', (e) => {
  const d = e.data;
  if (d && d.type === 'highlight' && typeof d.branch === 'string') highlighted = d.branch || null;
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

  /* highlight lerp — branches drift toward gold and back */
  for (const b of branches) {
    const active = highlighted === b.spec.key;
    b.tube.material.color.lerp(active ? GOLD_HL : b.baseColor, active ? 0.06 : 0.03);
  }

  controls.update();
  updateLabels();
  composer.render();
}

/* pause rendering when the tab is hidden (iframe embeds) */
document.addEventListener('visibilitychange', () => {
  renderer.setAnimationLoop(document.hidden ? null : tick);
  if (!document.hidden) clock.getDelta();
});
