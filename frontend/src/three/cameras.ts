import * as THREE from 'three'
import type { ReplayAngle, Sample } from '../types'
import { L, W, toWorld } from './world'

export type CameraMode = 'broadcast' | 'tactical' | 'follow' | ReplayAngle

export interface Shot {
  pos: THREE.Vector3
  target: THREE.Vector3
  /** metres visible across the frame at the target */
  width: number
}

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)

/** Damped spring: follows smoothly, never overshoots. */
class Spring {
  v = 0
  x: number
  constructor(x: number) {
    this.x = x
  }
  step(goal: number, w: number, dt: number) {
    this.v += (w * w * (goal - this.x) - 2 * w * this.v) * dt
    this.x += this.v * dt
    return this.x
  }
  snap(x: number) {
    this.x = x
    this.v = 0
  }
}

/** Operates the cameras the way a broadcast camera operator would. */
export class CameraDirector {
  private mode: CameraMode = 'broadcast'
  private x = new Spring(L / 2)
  private y = new Spring(W / 2)
  private width = new Spring(40)
  private prevBall: [number, number, number] | null = null
  private ballSpeed = 0
  private from: Shot | null = null
  private since = 0
  private last: Shot | null = null
  private fx = new Spring(L / 2)
  private fy = new Spring(W / 2)
  private rx = new Spring(L / 2)
  private ry = new Spring(W / 2)
  private snapped = true
  /** slot of the player a follow camera stays with */
  follow = -1
  /** x of the goal being attacked, for replays from behind it */
  goalX = L

  /** Change shot. A cut jumps straight to the new camera, as a vision mixer would. */
  setMode(mode: CameraMode, now: number, cut = false) {
    if (mode === this.mode) return
    this.from = cut ? null : this.last
    this.since = now
    this.mode = mode
    this.snapped = !cut
  }

  get current() {
    return this.mode
  }

  private broadcast(s: Sample | null, dt: number): Shot {
    if (s) {
      const [bx, by] = s.ball
      if (this.prevBall && s.tick > this.prevBall[2]) {
        const d = Math.hypot(bx - this.prevBall[0], by - this.prevBall[1])
        const v = d / ((s.tick - this.prevBall[2]) / 10)
        if (d < 10) this.ballSpeed += (v - this.ballSpeed) * Math.min(1, dt * 2)
      }
      this.prevBall = [bx, by, s.tick]
      if (!this.snapped && this.mode === 'broadcast') {
        this.x.snap(Math.min(88, Math.max(17, bx)))
        this.y.snap(18 + by * 0.32)
      }
      this.x.step(Math.min(88, Math.max(17, bx)), 1.7, dt)
      this.y.step(18 + by * 0.32, 1.5, dt)
      // widen when the ball travels, tighten when play is patient
      this.width.step(Math.min(58, 36 + this.ballSpeed * 1.1), 0.9, dt)
    }
    return {
      pos: toWorld(L / 2, -38, 23),
      target: toWorld(this.x.x, this.y.x, 0),
      width: this.width.x,
    }
  }

  /** A camera that stays with one player, the way a player cam does on a broadcast. */
  private followShot(s: Sample | null, dt: number): Shot {
    if (s && this.follow >= 0) {
      if (!this.snapped) {
        this.fx.snap(s.players[this.follow * 2])
        this.fy.snap(s.players[this.follow * 2 + 1])
      }
      this.fx.step(s.players[this.follow * 2], 2.2, dt)
      this.fy.step(s.players[this.follow * 2 + 1], 2.2, dt)
    }
    const x = this.fx.x
    const y = this.fy.x
    // high enough to clear the near stand whatever the player's position
    return { pos: toWorld(x, y - 22, 18), target: toWorld(x, y, 0.6), width: 28 }
  }

  /** Replay angles follow the ball closely; the scene has already happened, so they can afford to. */
  private replayShot(s: Sample | null, dt: number): Shot {
    if (s) {
      const [bx, by] = s.ball
      if (!this.snapped) {
        this.rx.snap(bx)
        this.ry.snap(by)
      }
      this.rx.step(bx, 2.4, dt)
      this.ry.step(by, 2.4, dt)
    }
    const bx = this.rx.x
    const by = this.ry.x
    const dir = this.goalX > L / 2 ? 1 : -1
    if (this.mode === 'behind_goal') {
      return { pos: toWorld(this.goalX + dir * 15, W / 2 + (by - W / 2) * 0.35, 6.5), target: toWorld(bx, by, 0.6), width: 30 }
    }
    if (this.mode === 'reverse') {
      // a pitch-side camera behind the far touchline, tracking along with play
      return { pos: toWorld(Math.min(L - 8, Math.max(8, bx)), W + 6.5, 6), target: toWorld(bx, by, 0.8), width: 34 }
    }
    return { pos: toWorld(bx - dir * 14, by - 26, 34), target: toWorld(bx + dir * 6, by, 0), width: 48 }
  }

  private tactical(): Shot {
    return { pos: toWorld(L / 2, -22, 92), target: toWorld(L / 2, W / 2 - 1.5, 0), width: 122 }
  }

  update(s: Sample | null, dt: number, now: number): Shot {
    const step = Math.min(dt, 0.1)
    const live = this.broadcast(s, step)
    const follow = this.followShot(s, step)
    const replay = this.replayShot(s, step)
    this.snapped = true
    let shot =
      this.mode === 'broadcast' ? live
        : this.mode === 'follow' ? follow
          : this.mode === 'tactical' ? this.tactical()
            : replay
    if (this.from) {
      const t = Math.min(1, (now - this.since) / 1100)
      const k = ease(t)
      shot = {
        pos: this.from.pos.clone().lerp(shot.pos, k),
        target: this.from.target.clone().lerp(shot.target, k),
        width: this.from.width + (shot.width - this.from.width) * k,
      }
      if (t >= 1) this.from = null
    }
    this.last = shot
    return shot
  }

  /** Point a perspective camera at a shot. */
  static apply(cam: THREE.PerspectiveCamera, shot: Shot) {
    cam.position.copy(shot.pos)
    cam.lookAt(shot.target)
    const dist = shot.pos.distanceTo(shot.target)
    const hfov = 2 * Math.atan(shot.width / 2 / dist)
    cam.fov = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(hfov / 2) / cam.aspect))
    cam.updateProjectionMatrix()
  }
}
