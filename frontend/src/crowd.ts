import { useEffect, useRef } from 'react'
import type { MatchEvent } from './types'

/**
 * Stadium sound, made in the browser from filtered noise: a steady murmur that
 * swells with the play, an "ooh" for big chances and a roar for goals. No
 * recordings, so nothing to license.
 */
class Crowd {
  private ctx = new AudioContext()
  private bed: GainNode
  private roar: GainNode
  private roarFilter: BiquadFilterNode

  constructor() {
    const ctx = this.ctx
    const noise = ctx.createBuffer(2, ctx.sampleRate * 4, ctx.sampleRate)
    for (let ch = 0; ch < 2; ch++) {
      // brown-ish noise: the low rumble of thousands of voices
      const d = noise.getChannelData(ch)
      let last = 0
      for (let i = 0; i < d.length; i++) {
        last = (last + 0.02 * (Math.random() * 2 - 1)) / 1.02
        d[i] = last * 3.2
      }
    }
    const source = (rate: number) => {
      const s = ctx.createBufferSource()
      s.buffer = noise
      s.loop = true
      s.playbackRate.value = rate
      s.start()
      return s
    }
    const master = ctx.createGain()
    master.gain.value = 0.9
    master.connect(ctx.destination)

    // the murmur, gently swelling
    const bedFilter = ctx.createBiquadFilter()
    bedFilter.type = 'bandpass'
    bedFilter.frequency.value = 520
    bedFilter.Q.value = 0.5
    this.bed = ctx.createGain()
    this.bed.gain.value = 0.12
    source(1).connect(bedFilter).connect(this.bed).connect(master)
    const lfo = ctx.createOscillator()
    lfo.frequency.value = 0.07
    const lfoGain = ctx.createGain()
    lfoGain.gain.value = 0.04
    lfo.connect(lfoGain).connect(this.bed.gain)
    lfo.start()

    // the roar: brighter, and silent until something happens
    this.roarFilter = ctx.createBiquadFilter()
    this.roarFilter.type = 'bandpass'
    this.roarFilter.frequency.value = 900
    this.roarFilter.Q.value = 0.4
    this.roar = ctx.createGain()
    this.roar.gain.value = 0
    source(1.6).connect(this.roarFilter).connect(this.roar).connect(master)
  }

  resume() {
    if (this.ctx.state !== 'running') this.ctx.resume().catch(() => {})
  }

  suspend() {
    if (this.ctx.state === 'running') this.ctx.suspend().catch(() => {})
  }

  swell(peak: number, attack: number, hold: number, release: number, brightness: number) {
    const t = this.ctx.currentTime
    const g = this.roar.gain
    g.cancelScheduledValues(t)
    g.setValueAtTime(g.value, t)
    g.linearRampToValueAtTime(peak, t + attack)
    g.setValueAtTime(peak, t + attack + hold)
    g.exponentialRampToValueAtTime(0.0001, t + attack + hold + release)
    const f = this.roarFilter.frequency
    f.cancelScheduledValues(t)
    f.setValueAtTime(f.value, t)
    f.linearRampToValueAtTime(brightness, t + attack)
    f.linearRampToValueAtTime(900, t + attack + hold + release)
  }

  react(e: MatchEvent) {
    if (e.type === 'goal') this.swell(0.75, 0.35, 4.5, 7, 1500)
    else if (e.type === 'shot' && (e.xg as number) >= 0.2) this.swell(0.35, 0.25, 0.9, 2.2, 1200)
    else if (e.type === 'shot') this.swell(0.18, 0.2, 0.4, 1.5, 1000)
    else if (e.type === 'corner') this.swell(0.1, 0.4, 0.6, 1.5, 950)
  }
}

export function useCrowd(events: MatchEvent[], enabled: boolean) {
  const crowd = useRef<Crowd | null>(null)
  const seen = useRef(0)

  useEffect(() => {
    if (enabled) {
      crowd.current ??= new Crowd()
      crowd.current.resume()
    } else crowd.current?.suspend()
  }, [enabled])

  useEffect(() => {
    const last = events.length ? events[events.length - 1].tick : 0
    if (last < seen.current - 50) seen.current = last // the viewer jumped back in the match
    if (enabled && crowd.current) {
      for (const e of events) {
        if (e.tick <= seen.current) continue
        crowd.current.react(e)
        // a log of crowd reactions, used when exporting a clip with sound
        const w = window as unknown as { __gantryCrowd?: unknown[] }
        if (['goal', 'shot', 'corner'].includes(e.type)) (w.__gantryCrowd ??= []).push({ t: performance.now(), type: e.type, xg: e.xg })
      }
    }
    seen.current = last
  }, [events, enabled])
}
