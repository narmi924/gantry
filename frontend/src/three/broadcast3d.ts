import * as THREE from 'three'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import type { MatchEvent, Player, Sample, Team } from '../types'
import { CameraDirector, type CameraMode } from './cameras'
import { PlayerRig } from './players'
import { ReplayLayer } from './replay'
import { buildStadium, type Stadium } from './stadium'
import { ANALYST_LAYER, Telestration } from './telestration'
import { L, W, toWorld } from './world'

export interface FrameInfo {
  teams: [Team, Team]
  lineup: (Player | undefined)[]
  events: MatchEvent[]
  /** team that scored most recently, and how many match seconds ago */
  goal: { team: number; age: number } | null
}

/** One camera of the broadcast, drawn into its own part of the canvas. */
export interface ViewSpec {
  id: string
  mode: CameraMode
  follow: number
  analyst: boolean
  /** CSS pixels, relative to the canvas */
  rect: { x: number; y: number; w: number; h: number }
}

export class View {
  readonly camera = new THREE.PerspectiveCamera(20, 16 / 9, 0.5, 600)
  readonly director = new CameraDirector()
  spec: ViewSpec

  constructor(spec: ViewSpec, now: number) {
    this.spec = spec
    this.director.setMode(spec.mode, now - 5000)
  }

  /** Screen position of a point on the pitch, in canvas CSS pixels, or null when off this view. */
  project(x: number, y: number, z: number) {
    const v = toWorld(x, y, z).project(this.camera)
    if (v.z > 1 || Math.abs(v.x) > 1.05 || Math.abs(v.y) > 1.05) return null
    const r = this.spec.rect
    return { x: r.x + ((v.x + 1) / 2) * r.w, y: r.y + ((1 - v.y) / 2) * r.h }
  }
}

function ballTexture() {
  const c = document.createElement('canvas')
  c.width = 256
  c.height = 128
  const ctx = c.getContext('2d')!
  ctx.fillStyle = '#f7f8fa'
  ctx.fillRect(0, 0, 256, 128)
  ctx.fillStyle = '#1d2733'
  for (let i = 0; i < 12; i++) {
    const x = (i % 6) * 44 + (i < 6 ? 10 : 32)
    const y = i < 6 ? 34 : 92
    ctx.beginPath()
    for (let k = 0; k < 5; k++) {
      const a = (k / 5) * Math.PI * 2 - Math.PI / 2
      ctx.lineTo(x + Math.cos(a) * 11, y + Math.sin(a) * 11)
    }
    ctx.fill()
  }
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  return t
}

/**
 * The 3D broadcast: a floodlit stadium and 22 animated players, filmed by one or
 * more cameras. A single view gets the full treatment (bloom); the monitor wall
 * draws several views of the same scene side by side.
 */
export class Broadcast3D {
  readonly renderer: THREE.WebGLRenderer
  readonly telestration = new Telestration()
  readonly replay = new ReplayLayer()
  views: View[] = []
  private scene = new THREE.Scene()
  private composer: EffectComposer
  private renderPass: RenderPass
  private stadium: Stadium
  private rigs: PlayerRig[] = []
  private ball: THREE.Mesh
  private prevBall: THREE.Vector3 | null = null
  private prevSample: Sample | null = null
  private time = 0
  private size = { w: 1, h: 1 }

  constructor(canvas: HTMLCanvasElement) {
    const r = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' })
    r.toneMapping = THREE.ACESFilmicToneMapping
    r.toneMappingExposure = 1.05
    r.shadowMap.enabled = true
    r.shadowMap.type = THREE.PCFSoftShadowMap
    r.shadowMap.autoUpdate = false
    this.renderer = r

    const scene = this.scene
    scene.background = new THREE.Color('#050b12')
    scene.fog = new THREE.FogExp2('#08121c', 0.0032)

    scene.add(new THREE.HemisphereLight('#2a3d55', '#0f2414', 0.55))
    scene.add(new THREE.AmbientLight('#ffffff', 0.12))
    // two banks of floodlights on the long roofs, each casting its own soft shadow
    for (const [y, intensity] of [[W + 40, 2.1], [-40, 1.5]] as const) {
      const light = new THREE.DirectionalLight('#fff6e8', intensity)
      toWorld(L / 2 + (y > 0 ? -20 : 25), y, 55, light.position)
      light.target.position.set(0, 0, 0)
      light.castShadow = true
      light.shadow.mapSize.set(4096, 4096)
      const sc = light.shadow.camera
      sc.left = -70
      sc.right = 70
      sc.top = 50
      sc.bottom = -50
      sc.near = 10
      sc.far = 200
      light.shadow.bias = -0.0003
      light.shadow.normalBias = 0.03
      light.shadow.radius = 3
      scene.add(light, light.target)
    }
    for (const x of [-40, L + 40]) {
      const light = new THREE.DirectionalLight('#eaf2ff', 0.45)
      toWorld(x, W / 2, 40, light.position)
      scene.add(light)
    }

    this.stadium = buildStadium(r)
    scene.add(this.stadium.group)
    scene.add(this.telestration.group, this.replay.group)

    for (let i = 0; i < 22; i++) {
      const rig = new PlayerRig()
      this.rigs.push(rig)
      scene.add(rig.group)
    }

    this.ball = new THREE.Mesh(
      new THREE.SphereGeometry(0.11, 24, 16),
      new THREE.MeshStandardMaterial({ map: ballTexture(), roughness: 0.45 }),
    )
    this.ball.castShadow = true
    scene.add(this.ball)

    const target = new THREE.WebGLRenderTarget(16, 16, { samples: 4, type: THREE.HalfFloatType })
    this.composer = new EffectComposer(r, target)
    this.renderPass = new RenderPass(scene, new THREE.PerspectiveCamera())
    this.composer.addPass(this.renderPass)
    this.composer.addPass(new UnrealBloomPass(new THREE.Vector2(16, 16), 0.55, 0.55, 0.9))
    this.composer.addPass(new OutputPass())
  }

  resize(width: number, height: number, dpr: number) {
    this.size = { w: width, h: height }
    this.renderer.setPixelRatio(dpr)
    this.renderer.setSize(width, height, false)
    this.composer.setPixelRatio(dpr)
    this.composer.setSize(width, height)
  }

  /** Add, update or drop views so they match `specs`, keeping each camera's motion. */
  setViews(specs: ViewSpec[], now: number, cut = false, goalX?: number) {
    const next: View[] = []
    for (const spec of specs) {
      const v = this.views.find((x) => x.spec.id === spec.id) ?? new View(spec, now)
      if (v.spec.mode !== spec.mode) v.director.setMode(spec.mode, now, cut)
      v.spec = spec
      v.director.follow = spec.follow
      if (goalX !== undefined) v.director.goalX = goalX
      next.push(v)
    }
    this.views = next
  }

  private updateScene(s: Sample | null, info: FrameInfo | null, dt: number, now: number) {
    this.time += dt
    this.stadium.update(this.time)
    if (!s || !info) return
    const [bx, by, bz] = s.ball
    for (let k = 0; k < 22; k++) {
      const player = info.lineup[k]
      const rig = this.rigs[k]
      if (player) rig.dress(player, info.teams[k < 11 ? 0 : 1], k === 0 || k === 11)
      rig.update(s.players[k * 2], s.players[k * 2 + 1], s.tick, bx, by, dt)
    }
    const pos = toWorld(bx, by, bz + 0.11)
    if (this.prevBall) {
      const d = pos.clone().sub(this.prevBall)
      d.y = 0
      const dist = d.length()
      if (dist > 0.001 && dist < 6) this.ball.rotateOnWorldAxis(new THREE.Vector3(d.z, 0, -d.x).normalize(), dist / 0.11)
    }
    this.ball.position.copy(pos)
    this.prevBall = pos
    // the home or away end jumps when their side scores
    const jump = info.goal && info.goal.age < 14 ? Math.max(0, 1 - info.goal.age / 14) : 0
    this.stadium.crowd.uHomeJump.value = info.goal?.team === 0 ? jump : 0
    this.stadium.crowd.uAwayJump.value = info.goal?.team === 1 ? jump : 0
    if (this.views.some((v) => v.spec.analyst)) this.telestration.update(s, info.events, now, this.prevSample)
    this.prevSample = s
  }

  frame(s: Sample | null, info: FrameInfo | null, dt: number, now: number) {
    this.updateScene(s, info, dt, now)
    const r = this.renderer
    r.shadowMap.needsUpdate = true
    for (const v of this.views) {
      v.camera.aspect = v.spec.rect.w / Math.max(1, v.spec.rect.h)
      CameraDirector.apply(v.camera, v.director.update(s, dt, now))
      if (v.spec.analyst) v.camera.layers.enable(ANALYST_LAYER)
      else v.camera.layers.disable(ANALYST_LAYER)
    }
    if (this.views.length === 1) {
      r.setScissorTest(false)
      this.renderPass.camera = this.views[0].camera
      this.composer.render(dt)
      return
    }
    // the monitor wall: every view into its own rectangle of the same canvas
    r.setScissorTest(true)
    r.setClearColor('#03070c')
    r.setViewport(0, 0, this.size.w, this.size.h)
    r.setScissor(0, 0, this.size.w, this.size.h)
    r.clear()
    for (const v of this.views) {
      const { x, y, w, h } = v.spec.rect
      const gy = this.size.h - y - h
      r.setViewport(x, gy, w, h)
      r.setScissor(x, gy, w, h)
      r.render(this.scene, v.camera)
    }
    r.setScissorTest(false)
  }

  dispose() {
    this.renderer.dispose()
  }
}
