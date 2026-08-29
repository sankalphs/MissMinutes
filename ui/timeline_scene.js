/*
 * MissMinutes temporal void — the sacred timeline as a glowing 3D spine
 * with branch timelines forking off into particle dust.
 *
 * Patterns adapted from three.js official examples (MIT):
 *   - postprocessing/bloom composer + ACES tone mapping  (webgl_postprocessing_unreal_bloom)
 *   - shader point sprites                               (webgl_points_waves)
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const VOID = 0x0b0a14;
const AMBER = 0xffb74a;
const AMBER_HOT = 0xffd9a0;
const CHRONOLINE = 0x8a86b8;
const CHRONO_DIM = 0x5b5680;
const DANGER = 0xe4572e;

const container = document.getElementById('scene-root');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

let renderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
} catch (e) {
  document.getElementById('fallback').hidden = false;
  throw e;
}

renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.1;
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(VOID, 0.055);
scene.background = new THREE.Color(VOID);

const camera = new THREE.PerspectiveCamera(46, window.innerWidth / window.innerHeight, 0.1, 200);
camera.position.set(0, 9.5, 21);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.minDistance = 7;
controls.maxDistance = 34;
controls.maxPolarAngle = Math.PI * 0.62;
controls.autoRotate = !reducedMotion;
controls.autoRotateSpeed = 0.5;
controls.target.set(0, 0.5, 0);

/* ------------------------------------------------------------------ */
/* Branch network — the one line that must not be pruned.             */
/* ------------------------------------------------------------------ */

const VOID_R = 90; // far dust shell radius (unused scalar, kept for tuning)

const spineCurve = new THREE.CatmullRomCurve3([
  new THREE.Vector3(0, 16, 0),
  new THREE.Vector3(0.6, 10, 0),
  new THREE.Vector3(-0.4, 4, 0),
  new THREE.Vector3(0, -2, 0),
  new THREE.Vector3(0.5, -8, 0),
  new THREE.Vector3(-0.3, -14, 0),
]);

const branchSpecs = [
  { name: 'WHAT IF...?', color: CHRONOLINE, side: -1, t: 0.28, reach: 1.0, pruned: false },
  { name: 'FOX X-MEN', color: CHRONOLINE, side: 1, t: 0.34, reach: 0.95, pruned: false },
  { name: 'SONY SPIDER-VERSE', color: CHRONO_DIM, side: -1, t: 0.46, reach: 0.8, pruned: false },
  { name: 'THE DEFENDERS', color: CHRONO_DIM, side: 1, t: 0.52, reach: 0.72, pruned: false },
  { name: 'PRUNED BRANCH', color: DANGER, side: 1, t: 0.7, reach: 0.6, pruned: true },
];

/* A branch forks off the spine at `origin`, drifting sideways/down and
   fading into the void. reach in [0,1] scales how far it wanders. */
function makeBranchCurve(origin, side, reach) {
  const dx = side * (6.5 + Math.random() * 2.5);
  const dz = (Math.random() - 0.5) * 7.0;
  const rel = [
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(0.3, -1.6, 0.35),
    new THREE.Vector3(0.62, -3.6, 0.8),
    new THREE.Vector3(0.85, -5.8, 1.25),
    new THREE.Vector3(1.0, -8.2, 1.7),
  ];
  const pts = rel.map((r) =>
    origin.clone().add(new THREE.Vector3(r.x * dx, r.y * reach, r.z * dz))
  );
  return new THREE.CatmullRomCurve3(pts);
}

const branches = [];
const labelAnchors = [];

/* --- glowing tube for a curve ------------------------------------- */
function tubeFor(curve, color, radius, opacity) {
  const geom = new THREE.TubeGeometry(curve, 64, radius, 10, false);
  const mat = new THREE.MeshBasicMaterial({
    color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false,
  });
  return new THREE.Mesh(geom, mat);
}

/* --- flowing particles along a curve (points + shader) ------------ */
const flowVert = `
  attribute float aOffset;
  uniform float uTime;
  varying float vFade;
  void main() {
    float t = fract(aOffset + uTime);
    vFade = smoothstep(0.0, 0.15, t) * (1.0 - smoothstep(0.8, 1.0, t));
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = (1.8 + vFade * 2.6) * (140.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;
const flowFrag = `
  uniform vec3 uColor;
  varying float vFade;
  void main() {
    if (length(gl_PointCoord - vec2(0.5)) > 0.5) discard;
    gl_FragColor = vec4(uColor * (0.45 + vFade), vFade * 0.9);
  }
`;

/* Particles slide along the curve: the CPU LUT re-samples each frame,
   the shader just fades head/tail. count kept small — 6 curves total. */
function flowFor(curve, color, count = 160, speed = 0.05) {
  const LUT = 256;
  const lut = curve.getSpacedPoints(LUT - 1);
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
    },
    vertexShader: flowVert,
    fragmentShader: flowFrag,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const points = new THREE.Points(geom, mat);
  points.userData = { speed, lut, count };
  return points;
}

function updateFlow(points, elapsed) {
  const { speed, lut, count } = points.userData;
  const LUT = lut.length;
  const pos = points.geometry.attributes.position.array;
  for (let i = 0; i < count; i++) {
    const t = (points.geometry.attributes.aOffset.array[i] + elapsed * speed) % 1;
    const idx = Math.min(LUT - 1, (t * LUT) | 0);
    pos[i * 3] = lut[idx].x;
    pos[i * 3 + 1] = lut[idx].y;
    pos[i * 3 + 2] = lut[idx].z;
  }
  points.geometry.attributes.position.needsUpdate = true;
}

/* --- sacred spine --------------------------------------------------- */
const spine = tubeFor(spineCurve, AMBER, 0.06, 0.85);
scene.add(spine);
const spineFlow = flowFor(spineCurve, AMBER_HOT, 220, 0.03);
scene.add(spineFlow);

/* --- loki anchor ---------------------------------------------------- */
const lokiGroup = new THREE.Group();
const lokiPos = spineCurve.getPointAt(0.82);
lokiGroup.position.copy(lokiPos);
scene.add(lokiGroup);

const lokiCore = new THREE.Mesh(
  new THREE.SphereGeometry(0.55, 32, 32),
  new THREE.MeshBasicMaterial({ color: AMBER_HOT })
);
lokiGroup.add(lokiCore);
const lokiGlow = new THREE.Mesh(
  new THREE.SphereGeometry(1.15, 32, 32),
  new THREE.MeshBasicMaterial({
    color: AMBER, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending, depthWrite: false,
  })
);
lokiGroup.add(lokiGlow);
const lokiHalo = new THREE.Mesh(
  new THREE.SphereGeometry(1.8, 32, 32),
  new THREE.MeshBasicMaterial({
    color: AMBER, transparent: true, opacity: 0.1, blending: THREE.AdditiveBlending, depthWrite: false,
  })
);
lokiGroup.add(lokiHalo);

/* --- branches ------------------------------------------------------- */
for (const spec of branchSpecs) {
  const origin = spineCurve.getPointAt(spec.t);
  const curve = makeBranchCurve(origin, spec.side, spec.reach);
  const baseOpacity = spec.pruned ? 0.5 : 0.5;
  const tube = tubeFor(curve, spec.color, spec.pruned ? 0.035 : 0.045, baseOpacity);
  scene.add(tube);
  const flow = flowFor(curve, spec.pruned ? DANGER : spec.color, 90, spec.pruned ? 0.09 : 0.05);
  scene.add(flow);
  const tip = curve.getPointAt(0.96);
  labelAnchors.push({ name: spec.name, pos: tip, pruned: spec.pruned, color: spec.color });
  branches.push({ spec, tube, flow, curve });
}

/* --- nixus/temporal dust (ambient particles in the void) ----------- */
const dustVert = `
  attribute float aScale;
  attribute vec3 aColor;
  varying vec3 vColor;
  uniform float uTime;
  void main() {
    vColor = aColor;
    vec3 pos = position;
    pos.y += sin(uTime * 0.25 + position.x * 1.7 + position.z * 0.9) * 0.5;
    vec4 mv = modelViewMatrix * vec4(pos, 1.0);
    gl_PointSize = aScale * (90.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;
const dustFrag = `
  varying vec3 vColor;
  void main() {
    if (length(gl_PointCoord - vec2(0.5)) > 0.5) discard;
    float d = length(gl_PointCoord - vec2(0.5));
    float alpha = smoothstep(0.5, 0.1, d);
    gl_FragColor = vec4(vColor, alpha * 0.55);
  }
`;

const DUST_COUNT = 900;
const dustPos = new Float32Array(DUST_COUNT * 3);
const dustScale = new Float32Array(DUST_COUNT);
const dustColor = new Float32Array(DUST_COUNT * 3);
const cAmber = new THREE.Color(AMBER);
const cChrono = new THREE.Color(CHRONOLINE);
for (let i = 0; i < DUST_COUNT; i++) {
  // shell around the spine — dust lives off to the sides
  const r = 14 + Math.random() * 26;
  const th = Math.random() * Math.PI * 2;
  dustPos[i * 3] = Math.cos(th) * r * (0.55 + Math.random() * 0.5);
  dustPos[i * 3 + 1] = (Math.random() - 0.5) * 46;
  dustPos[i * 3 + 2] = Math.sin(th) * r * (0.55 + Math.random() * 0.5);
  dustScale[i] = 0.8 + Math.random() * 2.2;
  const c = Math.random() < 0.25 ? cAmber : cChrono;
  dustColor[i * 3] = c.r; dustColor[i * 3 + 1] = c.g; dustColor[i * 3 + 2] = c.b;
}
const dustGeom = new THREE.BufferGeometry();
dustGeom.setAttribute('position', new THREE.BufferAttribute(dustPos, 3));
dustGeom.setAttribute('aScale', new THREE.BufferAttribute(dustScale, 1));
dustGeom.setAttribute('aColor', new THREE.BufferAttribute(dustColor, 3));
const dustMat = new THREE.ShaderMaterial({
  uniforms: { uTime: { value: 0 } },
  vertexShader: dustVert,
  fragmentShader: dustFrag,
  transparent: true,
  depthWrite: false,
  blending: THREE.AdditiveBlending,
});
const dust = new THREE.Points(dustGeom, dustMat);
scene.add(dust);

/* --- HTML labels (projected 3D -> 2D) ------------------------------- */
const labels = labelAnchors.map(({ name, pos, pruned }) => {
  const el = document.createElement('div');
  el.className = 'scene-label' + (pruned ? ' pruned' : '');
  el.textContent = name;
  container.appendChild(el);
  return { el, pos: pos.clone(), pruned };
});

/* --- projected 3D->2D labels ---------------------------------------- */
function updateLabels() {
  const v = new THREE.Vector3();
  for (const l of labels) {
    v.copy(l.pos).project(camera);
    const behind = v.z > 1;
    const x = (v.x * 0.5 + 0.5) * window.innerWidth;
    const y = (-v.y * 0.5 + 0.5) * window.innerHeight;
    const offscreen = x < -40 || x > window.innerWidth + 40 || y < 0 || y > window.innerHeight;
    l.el.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px)`;
    l.el.style.opacity = behind || offscreen ? '0' : '1';
  }
}

/* --- resize ---------------------------------------------------------- */
window.addEventListener('resize', onResize);
function onResize() {
  const w = window.innerWidth, h = window.innerHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  composer.setSize(w, h);
}

/* --- postprocessing --------------------------------------------------- */
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(window.innerWidth, window.innerHeight), 0.85, 0.55, 0.15);
composer.addPass(bloom);
composer.addPass(new OutputPass());

/* --- intro dolly ------------------------------------------------------ */
let introT = 0;
const INTRO_FRAMES = reducedMotion ? 0 : 120;
const introFrom = new THREE.Vector3(0, 26, 44);
const introTo = new THREE.Vector3(0, 9.5, 21);
if (!reducedMotion) camera.position.copy(introFrom);

/* --- animate ----------------------------------------------------------- */
const clock = new THREE.Clock();
let elapsed = 0;

renderer.setAnimationLoop(tick);

function tick() {
  const dt = Math.min(clock.getDelta(), 0.05);
  elapsed += dt;

  if (INTRO_FRAMES && introT < 1) {
    introT = Math.min(1, introT + dt * 0.5);
    const e = 1 - Math.pow(1 - introT, 3);
    camera.position.lerpVectors(introFrom, introTo, e);
  }

  spineFlow.material.uniforms.uTime.value = elapsed * spineFlow.userData.speed;
  updateFlow(spineFlow, elapsed);
  for (const b of branches) {
    b.flow.material.uniforms.uTime.value = elapsed * b.flow.userData.speed;
    updateFlow(b.flow, elapsed);
    if (b.spec.pruned) {
      // flicker: pruned branches gutter before they go
      const f = 0.35 + Math.abs(Math.sin(elapsed * 7.0)) * 0.65;
      b.tube.material.opacity = 0.25 + f * 0.3;
      b.flow.material.uniforms.uColor.value.setHex(DANGER).multiplyScalar(0.6 + f * 0.6);
    }
  }
  dustMat.uniforms.uTime.value = elapsed;

  // loki pulse
  const pulse = 1 + Math.sin(elapsed * 2.4) * 0.12;
  lokiCore.scale.setScalar(pulse);
  lokiGlow.scale.setScalar(1 + Math.sin(elapsed * 2.4) * 0.08);
  lokiHalo.scale.setScalar(1 + Math.sin(elapsed * 2.4) * 0.05);

  controls.update();
  updateLabels();
  composer.render();
}

/* pause rendering when the tab is hidden (iframe embeds) */
document.addEventListener('visibilitychange', () => {
  renderer.setAnimationLoop(document.hidden ? null : tick);
  if (!document.hidden) clock.getDelta();
});
