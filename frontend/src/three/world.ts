import * as THREE from 'three'

/** Pitch size in metres. The simulator works in x (length), y (width), z (height). */
export const L = 105
export const W = 68

/**
 * Simulator metres to Three.js world units. The main cameras sit on the
 * simulator's y < 0 side, looking towards +y, so x runs left to right on screen.
 */
export function toWorld(x: number, y: number, z = 0, out = new THREE.Vector3()) {
  return out.set(x - L / 2, z, W / 2 - y)
}

/** Deterministic random numbers, so the stadium is the same on every load. */
export function rng(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 4294967296
  }
}

export function hashString(s: string) {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}
