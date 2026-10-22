import * as THREE from 'three'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import type { Player, Team } from '../types'
import type { Action } from './actions'
import { hashString, toWorld } from './world'

const SKIN = ['#f3cfb0', '#e3b28c', '#c99169', '#ad7149', '#8c5536', '#6e4129', '#52301f']
const HAIR = ['#14100d', '#1c1511', '#2b1d14', '#4a3222', '#6b4a2b', '#c9a465']

// shared geometry: every player is built from the same parts
const G = {
  torso: new RoundedBoxGeometry(0.42, 0.54, 0.25, 3, 0.09),
  shorts: new RoundedBoxGeometry(0.38, 0.26, 0.24, 2, 0.07),
  thigh: new THREE.CapsuleGeometry(0.078, 0.3, 4, 10),
  shin: new THREE.CapsuleGeometry(0.062, 0.32, 4, 10),
  boot: new RoundedBoxGeometry(0.11, 0.08, 0.26, 2, 0.03),
  upperArm: new THREE.CapsuleGeometry(0.056, 0.2, 4, 8),
  forearm: new THREE.CapsuleGeometry(0.046, 0.2, 4, 8),
  hand: new THREE.SphereGeometry(0.05, 10, 8),
  head: new THREE.SphereGeometry(0.118, 18, 14),
  hair: new THREE.SphereGeometry(0.124, 18, 10, 0, Math.PI * 2, 0, Math.PI * 0.55),
  neck: new THREE.CylinderGeometry(0.05, 0.055, 0.1, 10),
  number: new THREE.PlaneGeometry(0.24, 0.24),
}

const materials = new Map<string, THREE.MeshStandardMaterial>()
function mat(color: string, roughness = 0.72) {
  const key = `${color}|${roughness}`
  let m = materials.get(key)
  if (!m) {
    m = new THREE.MeshStandardMaterial({ color, roughness })
    materials.set(key, m)
  }
  return m
}

function numberTexture(n: number, color: string) {
  const c = document.createElement('canvas')
  c.width = c.height = 128
  const ctx = c.getContext('2d')!
  ctx.fillStyle = color
  ctx.font = '800 96px Archivo, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(String(n), 64, 70)
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  return t
}

interface Limb {
  upper: THREE.Group
  lower: THREE.Group
}

function part(geo: THREE.BufferGeometry, m: THREE.Material, y = 0) {
  const mesh = new THREE.Mesh(geo, m)
  mesh.position.y = y
  mesh.castShadow = true
  return mesh
}

/** One footballer: a jointed figure that runs, turns and leans from the tracking data alone. */
export class PlayerRig {
  readonly group = new THREE.Group()
  private pelvis = new THREE.Group()
  private spine = new THREE.Group()
  private legs: Limb[] = []
  private arms: Limb[] = []
  private parts: Record<string, THREE.Mesh> = {}
  private numberMat = new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false })
  private phase = 0
  private yaw = 0
  private speed = 0
  private last: { x: number; y: number; tick: number } | null = null
  playerId = ''

  constructor() {
    this.group.add(this.pelvis)
    this.pelvis.position.y = 0.92
    const shorts = part(G.shorts, mat('#000'), -0.04)
    this.pelvis.add(shorts)
    this.parts.shorts = shorts

    for (const side of [1, -1]) {
      const hip = new THREE.Group()
      hip.position.set(side * 0.1, -0.08, 0)
      const thigh = part(G.thigh, mat('#000'), -0.21)
      const knee = new THREE.Group()
      knee.position.y = -0.42
      const shin = part(G.shin, mat('#000'), -0.21)
      const boot = part(G.boot, mat('#16191d', 0.5), -0.42)
      boot.position.z = 0.05
      knee.add(shin, boot)
      hip.add(thigh, knee)
      this.pelvis.add(hip)
      this.legs.push({ upper: hip, lower: knee })
      this.parts[`thigh${side}`] = thigh
      this.parts[`shin${side}`] = shin
    }

    this.spine.position.y = 0.04
    this.pelvis.add(this.spine)
    const torso = part(G.torso, mat('#000'), 0.27)
    this.spine.add(torso)
    this.parts.torso = torso
    const neck = part(G.neck, mat('#000'), 0.58)
    this.spine.add(neck)
    this.parts.neck = neck
    const head = part(G.head, mat('#000'), 0.69)
    const hair = part(G.hair, mat('#000', 0.9), 0.705)
    this.spine.add(head, hair)
    this.parts.head = head
    this.parts.hair = hair
    const number = new THREE.Mesh(G.number, this.numberMat)
    number.position.set(0, 0.32, -0.128)
    number.rotation.y = Math.PI
    this.spine.add(number)

    for (const side of [1, -1]) {
      const shoulder = new THREE.Group()
      shoulder.position.set(side * 0.255, 0.48, 0)
      shoulder.rotation.z = side * 0.12
      const upper = part(G.upperArm, mat('#000'), -0.13)
      const elbow = new THREE.Group()
      elbow.position.y = -0.27
      const fore = part(G.forearm, mat('#000'), -0.12)
      const hand = part(G.hand, mat('#000'), -0.25)
      elbow.add(fore, hand)
      shoulder.add(upper, elbow)
      this.spine.add(shoulder)
      this.arms.push({ upper: shoulder, lower: elbow })
      this.parts[`upper${side}`] = upper
      this.parts[`fore${side}`] = fore
      this.parts[`hand${side}`] = hand
    }
  }

  /** Dress the figure for a player. Called again when a substitute comes on. */
  dress(player: Player, team: Team, goalkeeper: boolean) {
    if (player.id === this.playerId) return
    this.playerId = player.id
    const c = team.colors
    const shirt = goalkeeper ? c.gk_shirt : c.shirt
    const shorts = goalkeeper ? c.gk_shorts : c.shorts
    const socks = goalkeeper ? c.gk_shirt : c.socks
    const h = hashString(player.id)
    const skin = mat(SKIN[h % SKIN.length], 0.6)
    const hair = mat(HAIR[(h >>> 4) % HAIR.length], 0.9)
    const p = this.parts
    p.torso.material = mat(shirt)
    p.shorts.material = mat(shorts)
    p.neck.material = skin
    p.head.material = skin
    p.hair.material = hair
    for (const s of [1, -1]) {
      p[`thigh${s}`].material = skin
      p[`shin${s}`].material = mat(socks)
      p[`upper${s}`].material = mat(shirt)
      p[`fore${s}`].material = goalkeeper ? mat(c.gk_shorts) : skin
      p[`hand${s}`].material = goalkeeper ? mat('#e9edf2', 0.6) : skin
    }
    this.numberMat.map?.dispose()
    this.numberMat.map = numberTexture(player.number, goalkeeper ? '#ffffff' : c.text)
    this.numberMat.needsUpdate = true
    this.last = null
  }

  /**
   * Place and animate the figure. `tick` is match time in tenths of a second, so
   * strides stay in step with the play at any playback speed.
   */
  update(x: number, y: number, tick: number, ballX: number, ballY: number, dt: number, action?: Action) {
    toWorld(x, y, 0, this.group.position)
    let moved = 0
    if (this.last && tick > this.last.tick) {
      const dx = x - this.last.x
      const dy = y - this.last.y
      moved = Math.hypot(dx, dy)
      const simDt = (tick - this.last.tick) / 10
      if (moved > 5) moved = 0 // a substitution or a new half, not a sprint
      const v = moved / simDt
      this.speed += (v - this.speed) * Math.min(1, simDt * 6)
      if (this.speed > 1.2 && moved > 0) this.turnTo(Math.atan2(dx, -dy), simDt * 9)
    }
    if (this.speed <= 1.2) this.turnTo(Math.atan2(ballX - x, -(ballY - y)), dt * 3)
    this.last = { x, y, tick }
    this.group.rotation.y = this.yaw

    const sp = this.speed
    const stride = 1.35 + 0.16 * sp
    this.phase += (2 * Math.PI * moved) / stride
    const run = Math.min(1, sp / 2)
    const amp = (0.18 + 0.075 * sp) * run
    const s = Math.sin(this.phase)
    const c = Math.cos(this.phase)
    this.legs[0].upper.rotation.x = -amp * s
    this.legs[1].upper.rotation.x = amp * s
    const knee = 0.12 + (0.35 + 0.1 * sp) * run
    this.legs[0].lower.rotation.x = knee * Math.max(0, c) + 0.06
    this.legs[1].lower.rotation.x = knee * Math.max(0, -c) + 0.06
    this.arms[0].upper.rotation.x = amp * 0.85 * s
    this.arms[1].upper.rotation.x = -amp * 0.85 * s
    const elbow = -(0.35 + 0.9 * run)
    this.arms[0].lower.rotation.x = elbow
    this.arms[1].lower.rotation.x = elbow
    this.spine.rotation.x = 0.03 + 0.018 * sp
    this.pelvis.position.y = 0.92 + 0.04 * Math.abs(s) * run - 0.03 * Math.min(1, sp / 7)
    this.group.rotation.z = 0
    this.arms[0].upper.rotation.z = 0.12
    this.arms[1].upper.rotation.z = -0.12
    if (action) this.act(action, tick, x, y, ballX, ballY)
  }

  /** A strike of the ball, or a goalkeeper's dive, laid over the run. */
  private act(a: Action, tick: number, x: number, y: number, ballX: number, ballY: number) {
    const u = (tick - a.at) / 4 // -1 .. 1 around the contact
    if (u < -1.6 || u > 2.2) return
    if (a.kind === 'kick') {
      // back-swing, strike, follow-through: the kicking leg swings from behind the body to in front of it
      const hip = u < 0 ? 0.85 * Math.min(1, (u + 1.6) / 1.2) : 0.85 - 2.1 * Math.min(1, u / 0.5)
      const recover = u > 0.8 ? Math.min(1, (u - 0.8) / 1.4) : 0
      const leg = this.legs[0]
      leg.upper.rotation.x = hip * (1 - recover)
      leg.lower.rotation.x = (u < 0 ? 1.25 : 0.15) * (1 - recover) + 0.06
      this.legs[1].upper.rotation.x = 0.1
      this.legs[1].lower.rotation.x = 0.18
      // arms out for balance, the body leaning back over the ball
      this.arms[0].upper.rotation.z = 0.7 * (1 - recover)
      this.arms[1].upper.rotation.z = -0.7 * (1 - recover)
      this.spine.rotation.x = -0.12 * (1 - recover)
      return
    }
    // a dive: the keeper lays out towards the ball, arms reaching
    const reach = u < 0 ? Math.max(0, 1 + u / 0.75) : u < 1.2 ? 1 : Math.max(0, 1 - (u - 1.2))
    const across = Math.cos(this.yaw) * (ballX - x) + Math.sin(this.yaw) * (ballY - y)
    const side = across === 0 ? a.side : Math.sign(across)
    this.group.rotation.z = -side * 1.25 * reach
    this.pelvis.position.y = 0.92 + 0.35 * reach
    for (const arm of this.arms) {
      arm.upper.rotation.x = -2.6 * reach
      arm.lower.rotation.x = -0.2 * reach
    }
    this.legs[0].upper.rotation.x = 0.3 * reach
    this.legs[1].upper.rotation.x = -0.25 * reach
  }

  private turnTo(target: number, rate: number) {
    let d = target - this.yaw
    while (d > Math.PI) d -= Math.PI * 2
    while (d < -Math.PI) d += Math.PI * 2
    this.yaw += d * Math.min(1, rate)
  }
}
