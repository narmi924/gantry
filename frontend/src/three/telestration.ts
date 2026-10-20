import * as THREE from 'three'
import type { MatchEvent, Sample } from '../types'
import { L, W, toWorld } from './world'

/** Objects on this layer are only seen by cameras of feeds that ask for analysis. */
export const ANALYST_LAYER = 1

const HOME = new THREE.Color('#3b6cff')
const AWAY = new THREE.Color('#f2a516')

/**
 * Drawings on the grass for the analyst's feed, all worked out from the tracking data:
 * who controls which space, the defensive line, the last pass and its difficulty, and
 * the pressure on the ball.
 */
export class Telestration {
  readonly group = new THREE.Group()
  private space: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>
  private line: THREE.Mesh
  private pass: THREE.Mesh | null = null
  private passId = -1
  private pressure: THREE.Mesh[] = []
  private spaceOn = 0
  /** the pass currently drawn, for its label */
  lastPass: MatchEvent | null = null

  constructor() {
    const uniforms = {
      uPlayers: { value: Array.from({ length: 22 }, () => new THREE.Vector4()) },
      uOpacity: { value: 0 },
      uHome: { value: HOME },
      uAway: { value: AWAY },
    }
    const mat = new THREE.ShaderMaterial({
      uniforms,
      transparent: true,
      depthWrite: false,
      vertexShader: `
        varying vec2 vSim;
        void main() {
          vec4 w = modelMatrix * vec4(position, 1.0);
          vSim = vec2(w.x + ${(L / 2).toFixed(1)}, ${(W / 2).toFixed(1)} - w.z);
          gl_Position = projectionMatrix * viewMatrix * w;
        }`,
      fragmentShader: `
        uniform vec4 uPlayers[22];
        uniform float uOpacity;
        uniform vec3 uHome;
        uniform vec3 uAway;
        varying vec2 vSim;
        void main() {
          float th = 1e6;
          float ta = 1e6;
          for (int i = 0; i < 22; i++) {
            // where the player will be in half a second, then time to reach this patch
            vec2 p = uPlayers[i].xy + uPlayers[i].zw * 0.5;
            float t = length(vSim - p) / 7.0;
            if (i < 11) th = min(th, t); else ta = min(ta, t);
          }
          float d = ta - th;
          float control = tanh(d * 1.6);
          vec3 col = d > 0.0 ? uHome : uAway;
          float a = smoothstep(0.15, 0.9, abs(control)) * 0.42;
          float edge = 1.0 - smoothstep(0.0, 0.05, abs(d));
          gl_FragColor = vec4(mix(col, vec3(1.0), edge * 0.8), uOpacity * max(a, edge * 0.75));
        }`,
    })
    this.space = new THREE.Mesh(new THREE.PlaneGeometry(L, W, 1, 1), mat)
    this.space.rotation.x = -Math.PI / 2
    toWorld(L / 2, W / 2, 0.03, this.space.position)
    this.space.renderOrder = 2

    this.line = new THREE.Mesh(
      new THREE.PlaneGeometry(0.22, W),
      new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0.75, depthWrite: false }),
    )
    this.line.rotation.x = -Math.PI / 2
    this.line.renderOrder = 3

    for (let i = 0; i < 2; i++) {
      const m = new THREE.Mesh(
        new THREE.PlaneGeometry(1, 0.16),
        new THREE.MeshBasicMaterial({ color: '#ff5a4f', transparent: true, opacity: 0, depthWrite: false }),
      )
      m.rotation.x = -Math.PI / 2
      m.renderOrder = 3
      this.pressure.push(m)
    }
    this.group.add(this.space, this.line, ...this.pressure)
    this.group.traverse((o) => o.layers.set(ANALYST_LAYER))
  }

  /** Show the space map for a few seconds (the director calls it). */
  showSpace(seconds: number, now: number) {
    this.spaceOn = now + seconds * 1000
  }

  update(s: Sample | null, events: MatchEvent[], now: number, prev: Sample | null) {
    if (!s) return
    // space: fade in while the director has it on air
    const target = now < this.spaceOn ? 1 : 0
    const u = this.space.material.uniforms
    u.uOpacity.value += (target - u.uOpacity.value) * 0.08
    this.space.visible = u.uOpacity.value > 0.01
    if (this.space.visible) {
      const dt = prev && s.tick > prev.tick ? (s.tick - prev.tick) / 10 : 0
      for (let k = 0; k < 22; k++) {
        const x = s.players[k * 2]
        const y = s.players[k * 2 + 1]
        const vx = dt > 0 && prev ? (x - prev.players[k * 2]) / dt : 0
        const vy = dt > 0 && prev ? (y - prev.players[k * 2 + 1]) / dt : 0
        u.uPlayers.value[k].set(x, y, Math.abs(vx) < 12 ? vx : 0, Math.abs(vy) < 12 ? vy : 0)
      }
    }

    // the defensive line of the side without the ball
    const owner = s.owner
    if (owner >= 0) {
      const defending = owner < 11 ? 1 : 0
      const forward = (defending === 0) === (s.period === 1)
      let deepest = forward ? Infinity : -Infinity
      for (let k = defending * 11 + 1; k < defending * 11 + 11; k++) {
        const x = s.players[k * 2]
        deepest = forward ? Math.min(deepest, x) : Math.max(deepest, x)
      }
      toWorld(deepest, W / 2, 0.035, this.line.position)
      this.line.visible = true
      ;(this.line.material as THREE.MeshBasicMaterial).color.set(defending === 0 ? HOME : AWAY).lerp(new THREE.Color('#fff'), 0.45)

      // pressure: the two nearest opponents closing the ball down
      const cx = s.players[owner * 2]
      const cy = s.players[owner * 2 + 1]
      const opp: { k: number; d: number }[] = []
      for (let k = defending * 11; k < defending * 11 + 11; k++) {
        const dx = s.players[k * 2] - cx
        const dy = s.players[k * 2 + 1] - cy
        opp.push({ k, d: Math.hypot(dx, dy) })
      }
      opp.sort((a, b) => a.d - b.d)
      this.pressure.forEach((m, i) => {
        const o = opp[i]
        const mat = m.material as THREE.MeshBasicMaterial
        if (!o || o.d > 7) {
          mat.opacity = 0
          return
        }
        const ox = s.players[o.k * 2]
        const oy = s.players[o.k * 2 + 1]
        const a = toWorld(cx, cy, 0.04)
        const b = toWorld(ox, oy, 0.04)
        m.position.copy(a).add(b).multiplyScalar(0.5)
        m.scale.x = Math.max(0.1, a.distanceTo(b))
        m.rotation.z = Math.atan2(b.z - a.z, b.x - a.x) * -1
        mat.opacity = 0.85 * (1 - o.d / 7)
      })
    } else {
      this.line.visible = false
      this.pressure.forEach((m) => ((m.material as THREE.MeshBasicMaterial).opacity = 0))
    }

    // the last pass, for a couple of seconds after it arrives
    let latest: MatchEvent | null = null
    for (let i = events.length - 1; i >= 0 && i > events.length - 25; i--) {
      const e = events[i]
      if (e.type === 'pass' && e.outcome === 'complete') {
        latest = e
        break
      }
    }
    const fresh = latest && s.tick - latest.tick < 30 ? latest : null
    if (fresh && fresh.id !== this.passId) {
      this.passId = fresh.id
      if (this.pass) {
        this.group.remove(this.pass)
        this.pass.geometry.dispose()
      }
      const a = toWorld(fresh.x as number, fresh.y as number, 0.05)
      const b = toWorld(fresh.end_x as number, fresh.end_y as number, 0.05)
      const len = fresh.length as number
      const mid = a.clone().add(b).multiplyScalar(0.5)
      mid.y = (fresh.lofted ? 0.18 : 0.05) * len + 0.3
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b)
      const hard = Math.min(1, (fresh.difficulty as number) / 60)
      const color = new THREE.Color('#ffffff').lerp(new THREE.Color('#ffb02e'), hard)
      this.pass = new THREE.Mesh(
        new THREE.TubeGeometry(curve, 32, 0.09, 6, false),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95, depthWrite: false }),
      )
      this.pass.layers.set(ANALYST_LAYER)
      this.group.add(this.pass)
    }
    this.lastPass = fresh
    if (this.pass) {
      this.pass.visible = !!fresh
      if (fresh) (this.pass.material as THREE.MeshBasicMaterial).opacity = 0.95 * (1 - (s.tick - fresh.tick) / 30)
    }
  }
}
