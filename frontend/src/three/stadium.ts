import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { L, W, rng, toWorld } from './world'

const X0 = -6
const X1 = L + 6
const Y0 = -5
const Y1 = W + 5

/** Grass with mowing stripes and every marking painted in, at about 35 pixels per metre. */
function pitchTexture(maxAnisotropy: number) {
  const ppm = 35
  const canvas = document.createElement('canvas')
  canvas.width = Math.round((X1 - X0) * ppm)
  canvas.height = Math.round((Y1 - Y0) * ppm)
  const ctx = canvas.getContext('2d')!
  const px = (x: number) => (x - X0) * ppm
  const py = (y: number) => (Y1 - y) * ppm

  ctx.fillStyle = '#255f2e'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  const stripes = 18
  for (let i = 0; i < stripes; i++) {
    const a = (L / stripes) * i
    const b = (L / stripes) * (i + 1)
    ctx.fillStyle = i % 2 ? '#2b7135' : '#30803c'
    ctx.fillRect(px(a), py(W), (b - a) * ppm, W * ppm)
  }
  // fine variation in the turf, and wear in the goalmouths
  const r = rng(77)
  for (let i = 0; i < 90000; i++) {
    const x = r() * canvas.width
    const y = r() * canvas.height
    const light = r() > 0.5
    ctx.fillStyle = light ? 'rgba(255,255,220,0.035)' : 'rgba(0,20,0,0.05)'
    ctx.fillRect(x, y, 2 + r() * 5, 1 + r() * 2)
  }
  for (const gx of [3, L - 3]) {
    const g = ctx.createRadialGradient(px(gx), py(W / 2), 0, px(gx), py(W / 2), 7 * ppm)
    g.addColorStop(0, 'rgba(120,110,60,0.22)')
    g.addColorStop(1, 'rgba(120,110,60,0)')
    ctx.fillStyle = g
    ctx.fillRect(px(gx - 8), py(W / 2 + 8), 16 * ppm, 16 * ppm)
  }

  ctx.strokeStyle = 'rgba(246,250,244,0.95)'
  ctx.fillStyle = 'rgba(246,250,244,0.95)'
  ctx.lineWidth = 0.12 * ppm
  const rect = (x0: number, y0: number, x1: number, y1: number) => ctx.strokeRect(px(x0), py(y1), (x1 - x0) * ppm, (y1 - y0) * ppm)
  const arc = (cx: number, cy: number, rad: number, a0: number, a1: number) => {
    ctx.beginPath()
    // canvas y runs downward, so angles flip sign
    ctx.arc(px(cx), py(cy), rad * ppm, -a1, -a0)
    ctx.stroke()
  }
  const dot = (x: number, y: number, rad: number) => {
    ctx.beginPath()
    ctx.arc(px(x), py(y), rad * ppm, 0, Math.PI * 2)
    ctx.fill()
  }
  rect(0, 0, L, W)
  ctx.beginPath()
  ctx.moveTo(px(L / 2), py(0))
  ctx.lineTo(px(L / 2), py(W))
  ctx.stroke()
  arc(L / 2, W / 2, 9.15, 0, Math.PI * 2)
  dot(L / 2, W / 2, 0.2)
  const a = Math.acos(5.5 / 9.15)
  for (const side of [0, 1]) {
    const gx = side ? L : 0
    const dir = side ? -1 : 1
    rect(Math.min(gx, gx + dir * 16.5), W / 2 - 20.16, Math.max(gx, gx + dir * 16.5), W / 2 + 20.16)
    rect(Math.min(gx, gx + dir * 5.5), W / 2 - 9.16, Math.max(gx, gx + dir * 5.5), W / 2 + 9.16)
    dot(gx + dir * 11, W / 2, 0.2)
    if (side) arc(L - 11, W / 2, 9.15, Math.PI - a, Math.PI + a)
    else arc(11, W / 2, 9.15, -a, a)
  }
  arc(0, 0, 1, 0, Math.PI / 2)
  arc(0, W, 1, -Math.PI / 2, 0)
  arc(L, 0, 1, Math.PI / 2, Math.PI)
  arc(L, W, 1, Math.PI, Math.PI * 1.5)

  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = maxAnisotropy
  tex.generateMipmaps = true
  tex.minFilter = THREE.LinearMipmapLinearFilter
  return tex
}

function goal(side: number) {
  const g = new THREE.Group()
  const post = new THREE.MeshStandardMaterial({ color: '#f4f6f8', roughness: 0.35 })
  const r = 0.06
  const H = 2.44
  const half = 3.66
  const depth = 2.0
  const gx = side ? L : 0
  const out = side ? 1 : -1
  const cyl = (len: number) => new THREE.CylinderGeometry(r, r, len, 12)
  for (const s of [-1, 1]) {
    const m = new THREE.Mesh(cyl(H), post)
    toWorld(gx, W / 2 + s * half, H / 2, m.position)
    m.castShadow = true
    g.add(m)
  }
  const bar = new THREE.Mesh(cyl(half * 2 + r * 2), post)
  toWorld(gx, W / 2, H, bar.position)
  bar.rotation.x = Math.PI / 2
  bar.castShadow = true
  g.add(bar)

  // the net: a grid of fine lines over the back, roof and sides
  const pts: number[] = []
  const P = (x: number, y: number, z: number) => {
    const v = toWorld(x, y, z)
    pts.push(v.x, v.y, v.z)
  }
  const back = gx + out * depth
  const topBack = 1.7
  const step = 0.25
  for (let y = W / 2 - half; y <= W / 2 + half + 1e-6; y += step) {
    P(gx, y, H); P(back, y, topBack)
    P(back, y, topBack); P(back, y, 0)
  }
  for (let z = 0; z <= topBack + 1e-6; z += step) {
    P(back, W / 2 - half, z); P(back, W / 2 + half, z)
  }
  for (let t = 0; t <= 1 + 1e-6; t += step / depth) {
    const x = gx + out * depth * t
    const z = H + (topBack - H) * t
    P(x, W / 2 - half, z); P(x, W / 2 + half, z)
    for (const s of [-1, 1]) {
      P(x, W / 2 + s * half, 0); P(x, W / 2 + s * half, z)
    }
  }
  for (const s of [-1, 1]) {
    for (let z = 0; z <= H + 1e-6; z += step) {
      const t = z > topBack ? (H - z) / (H - topBack) : 1
      P(gx, W / 2 + s * half, z); P(gx + out * depth * t, W / 2 + s * half, Math.min(z, topBack + (z - topBack)))
    }
  }
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
  g.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: '#e8eef2', transparent: true, opacity: 0.45 })))
  return g
}

function ledTexture() {
  const c = document.createElement('canvas')
  c.width = 2048
  c.height = 64
  const ctx = c.getContext('2d')!
  ctx.fillStyle = '#081624'
  ctx.fillRect(0, 0, c.width, c.height)
  const items: [string, string][] = [['Kingsmere FC', '#3b6cff'], ['Ashvale Athletic', '#f2a516'], ['Matchday', '#9fb3c8']]
  ctx.font = '700 40px Archivo, sans-serif'
  ctx.textBaseline = 'middle'
  let x = 20
  let i = 0
  while (x < c.width) {
    const [label, color] = items[i % items.length]
    ctx.fillStyle = color
    ctx.fillText(label, x, 34)
    x += ctx.measureText(label).width + 90
    i++
  }
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.wrapS = THREE.RepeatWrapping
  return tex
}

export interface CrowdUniforms {
  uTime: { value: number }
  uHomeJump: { value: number }
  uAwayJump: { value: number }
}

/** Stands full of supporters, one instanced draw call. Home fans in blue, the away end in amber. */
function crowd(): { mesh: THREE.InstancedMesh; uniforms: CrowdUniforms } {
  const r = rng(20261020)
  const seats: { x: number; y: number; z: number; color: string; side: number }[] = []
  // under floodlights a crowd reads as dark, with team colour in it, not as bright tiles
  const HOME = ['#15306f', '#1d40a0', '#122655', '#1a2230', '#232c3a', '#1d2532', '#6f7a8c']
  const AWAY = ['#a8720f', '#c98a12', '#232c3a', '#1a2230', '#6f6656']
  const NEUTRAL = ['#1a2230', '#232c3a', '#2c3544', '#3a4453', '#151b25', '#59606c']
  const pick = (p: string[]) => p[Math.floor(r() * p.length)]
  const add = (x: number, y: number, z: number, palette: string[], side: number) => {
    if (r() < 0.05) return
    seats.push({ x: x + (r() - 0.5) * 0.15, y, z, color: pick(palette), side })
  }
  // long stands along both touchlines
  for (const near of [false, true]) {
    for (let row = 0; row < 34; row++) {
      const d = 8 + row * 0.82
      const z = 1.2 + row * 0.52
      for (let x = -9; x < L + 9; x += 0.56) {
        const y = near ? -d : W + d
        const home = r() < (x < L * 0.75 ? 0.72 : 0.4)
        add(x, y, z, home ? HOME : NEUTRAL, home ? 1 : 0)
      }
    }
  }
  // ends; the away supporters sit behind the right-hand goal
  for (const right of [false, true]) {
    for (let row = 0; row < 30; row++) {
      const d = 8 + row * 0.82
      const z = 1.2 + row * 0.52
      for (let y = -6; y < W + 6; y += 0.56) {
        const x = right ? L + d : -d
        const away = right && y > 14 && y < 54
        const home = !away && r() < 0.65
        add(x, y, z, away ? AWAY : home ? HOME : NEUTRAL, away ? -1 : home ? 1 : 0)
      }
    }
  }

  // a person: shoulders and a head
  const body = new THREE.BoxGeometry(0.38, 0.5, 0.26)
  body.translate(0, 0.25, 0)
  const head = new THREE.BoxGeometry(0.17, 0.19, 0.18)
  head.translate(0, 0.62, 0)
  const geo = mergeGeometries([body, head])!
  const mat = new THREE.MeshStandardMaterial({ roughness: 1 })
  const uniforms: CrowdUniforms = { uTime: { value: 0 }, uHomeJump: { value: 0 }, uAwayJump: { value: 0 } }
  const rand = new Float32Array(seats.length)
  const side = new Float32Array(seats.length)
  const mesh = new THREE.InstancedMesh(geo, mat, seats.length)
  const m = new THREE.Matrix4()
  const v = new THREE.Vector3()
  const col = new THREE.Color()
  seats.forEach((s, i) => {
    toWorld(s.x, s.y, s.z, v)
    const tall = 0.85 + r() * 0.3
    m.makeScale(0.9 + r() * 0.2, tall, 1).setPosition(v.x, v.y, v.z)
    mesh.setMatrixAt(i, m)
    mesh.setColorAt(i, col.set(s.color))
    rand[i] = r()
    side[i] = s.side
  })
  geo.setAttribute('aRand', new THREE.InstancedBufferAttribute(rand, 1))
  geo.setAttribute('aSide', new THREE.InstancedBufferAttribute(side, 1))
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms)
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nattribute float aRand;\nattribute float aSide;\nuniform float uTime;\nuniform float uHomeJump;\nuniform float uAwayJump;')
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        float jump = aSide > 0.5 ? uHomeJump : (aSide < -0.5 ? uAwayJump : uHomeJump * 0.3);
        float idle = 0.03 * sin(uTime * 1.7 + aRand * 40.0);
        transformed.y += idle + jump * abs(sin(uTime * 8.5 + aRand * 6.2831)) * 0.38;`)
  }
  mesh.frustumCulled = false
  return { mesh, uniforms }
}

export interface Stadium {
  group: THREE.Group
  crowd: CrowdUniforms
  led: THREE.Texture
  update(time: number): void
}

export function buildStadium(renderer: THREE.WebGLRenderer): Stadium {
  const group = new THREE.Group()

  // the ground beyond the pitch, then the pitch itself
  const surround = new THREE.Mesh(
    new THREE.PlaneGeometry(260, 220),
    new THREE.MeshStandardMaterial({ color: '#0d1912', roughness: 1 }),
  )
  surround.rotation.x = -Math.PI / 2
  surround.position.y = -0.02
  surround.receiveShadow = true
  group.add(surround)

  const pitch = new THREE.Mesh(
    new THREE.PlaneGeometry(X1 - X0, Y1 - Y0),
    new THREE.MeshStandardMaterial({ map: pitchTexture(renderer.capabilities.getMaxAnisotropy()), roughness: 0.92 }),
  )
  pitch.rotation.x = -Math.PI / 2
  toWorld((X0 + X1) / 2, (Y0 + Y1) / 2, 0, pitch.position)
  pitch.receiveShadow = true
  group.add(pitch)

  group.add(goal(0), goal(1))

  // corner flags
  const flagPole = new THREE.MeshStandardMaterial({ color: '#f2f2f2' })
  const flagCloth = new THREE.MeshStandardMaterial({ color: '#e8c33a', side: THREE.DoubleSide, roughness: 0.8 })
  for (const [x, y] of [[0, 0], [0, W], [L, 0], [L, W]]) {
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 1.5, 6), flagPole)
    toWorld(x, y, 0.75, pole.position)
    const cloth = new THREE.Mesh(new THREE.PlaneGeometry(0.35, 0.25), flagCloth)
    toWorld(x, y, 1.35, cloth.position)
    cloth.position.x += 0.18
    pole.castShadow = true
    group.add(pole, cloth)
  }

  // LED boards around the pitch, scrolling club names. Each board faces the pitch.
  const led = ledTexture()
  const ledTextures: THREE.Texture[] = []
  const boardBack = new THREE.MeshStandardMaterial({ color: '#0a1520', roughness: 0.6 })
  const board = (x0: number, y0: number, x1: number, y1: number) => {
    const len = Math.hypot(x1 - x0, y1 - y0)
    const tex = led.clone()
    tex.repeat.set(len / 40, 1)
    ledTextures.push(tex)
    const face = new THREE.MeshStandardMaterial({ color: '#000', emissive: '#ffffff', emissiveMap: tex, emissiveIntensity: 0.9 })
    const m = new THREE.Mesh(new THREE.BoxGeometry(len, 0.9, 0.12), [boardBack, boardBack, boardBack, boardBack, face, boardBack])
    toWorld((x0 + x1) / 2, (y0 + y1) / 2, 0.45, m.position)
    m.rotation.y = -Math.atan2(y1 - y0, x1 - x0)
    group.add(m)
  }
  board(-2, 72, L + 2, 72)
  board(L + 2, -4, -2, -4)
  board(-5, W + 2, -5, -2)
  board(L + 5, -2, L + 5, W + 2)

  // terraces under the supporters, from the front row up to the back row
  const terrace = new THREE.MeshStandardMaterial({ color: '#111c27', roughness: 0.95, side: THREE.DoubleSide })
  const quad = (pts: [number, number, number][]) => {
    const v = pts.map(([x, y, z]) => toWorld(x, y, z))
    const geo = new THREE.BufferGeometry().setFromPoints([v[0], v[1], v[2], v[0], v[2], v[3]])
    geo.computeVertexNormals()
    group.add(new THREE.Mesh(geo, terrace))
  }
  const front = 7.6
  const back = 8 + 34 * 0.82
  const zf = 1.0
  const zb = 1.2 + 34 * 0.52
  quad([[-10, W + front, zf], [L + 10, W + front, zf], [L + 10, W + back, zb], [-10, W + back, zb]])
  quad([[-10, -front, zf], [L + 10, -front, zf], [L + 10, -back, zb], [-10, -back, zb]])
  quad([[-front, -8, zf], [-front, W + 8, zf], [-back, W + 8, zb], [-back, -8, zb]])
  quad([[L + front, -8, zf], [L + front, W + 8, zf], [L + back, W + 8, zb], [L + back, -8, zb]])
  // a low wall in front of each stand
  const wall = new THREE.MeshStandardMaterial({ color: '#0c1823', roughness: 0.8 })
  for (const [x0, y0, x1, y1] of [[-10, W + front, L + 10, W + front], [-10, -front, L + 10, -front], [-front, -8, -front, W + 8], [L + front, -8, L + front, W + 8]]) {
    const len = Math.hypot(x1 - x0, y1 - y0)
    const m = new THREE.Mesh(new THREE.BoxGeometry(len, 1.2, 0.3), wall)
    toWorld((x0 + x1) / 2, (y0 + y1) / 2, 0.6, m.position)
    m.rotation.y = -Math.atan2(y1 - y0, x1 - x0)
    group.add(m)
  }

  const { mesh, uniforms } = crowd()
  group.add(mesh)

  // roof edges, lit by the floodlight strips
  const roof = new THREE.MeshStandardMaterial({ color: '#0b141d', roughness: 0.8 })
  const lamp = new THREE.MeshStandardMaterial({ color: '#000', emissive: '#fff8e6', emissiveIntensity: 6 })
  const roofPiece = (x0: number, y0: number, x1: number, y1: number, depth: number) => {
    const len = Math.hypot(x1 - x0, y1 - y0)
    const rot = -Math.atan2(y1 - y0, x1 - x0)
    const g = new THREE.Group()
    const slabMesh = new THREE.Mesh(new THREE.BoxGeometry(len, 0.8, depth), roof)
    slabMesh.position.z = -depth / 2
    const strip = new THREE.Mesh(new THREE.BoxGeometry(len * 0.92, 0.35, 0.5), lamp)
    strip.position.set(0, -0.55, -0.4)
    g.add(slabMesh, strip)
    toWorld((x0 + x1) / 2, (y0 + y1) / 2, 30, g.position)
    g.rotation.y = rot
    group.add(g)
  }
  roofPiece(-12, W + 22, L + 12, W + 22, 26)
  roofPiece(L + 12, -22, -12, -22, 26)
  roofPiece(-22, W + 10, -22, -10, 22)
  roofPiece(L + 22, -10, L + 22, W + 10, 22)

  return {
    group,
    crowd: uniforms,
    led,
    update(time: number) {
      uniforms.uTime.value = time
      for (const t of ledTextures) t.offset.x = (time * 0.02) % 1
    },
  }
}
