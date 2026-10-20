import { useEffect, useState } from 'react'
import { AskBox } from './components/AskBox'
import { Controls } from './components/Controls'
import { Stage, type Layout } from './components/Stage'
import { Talkback } from './components/Talkback'
import { useCrowd } from './crowd'
import { FEEDS, type FeedId } from './types'
import { useFeed } from './useFeed'

const ALL_FEEDS = FEEDS.map((f) => f.id)

function initial() {
  const q = new URLSearchParams(location.search)
  const feed = (FEEDS.find((f) => f.id === q.get('feed'))?.id ?? 'casual_en') as FeedId
  const layout: Layout = q.get('view') === 'wall' ? 'wall' : 'single'
  return { feed, layout }
}

export default function App() {
  const { feed, snap } = useFeed('demo', ALL_FEEDS)
  const [tactical, setTactical] = useState(false)
  const [showStats, setShowStats] = useState(false)
  const [selected, setSelected] = useState<FeedId>(() => initial().feed)
  const [layout, setLayout] = useState<Layout>(() => initial().layout)
  const [sound, setSound] = useState(false)
  const meta = snap.meta
  useCrowd(snap.events, sound && snap.speed <= 1.25)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.code === 'Space') {
        e.preventDefault()
        feed.setPlaying(!feed.snapshot.playing)
      } else if (e.key === 't') setTactical((v) => !v)
      else if (e.key === 's') setShowStats((v) => !v)
      else if (e.key === 'm') setSound((v) => !v)
      else if (e.key === 'g') setLayout((v) => (v === 'wall' ? 'single' : 'wall'))
      else if (/^[1-4]$/.test(e.key)) setSelected(FEEDS[Number(e.key) - 1].id)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [feed])

  return (
    <div className={`app app-${layout}`}>
      <header className="top">
        <div className="brand">Gantry</div>
        {meta && (
          <div className="fixture">
            <span>{meta.teams[0].name}</span>
            <span className="fixture-v">v</span>
            <span>{meta.teams[1].name}</span>
          </div>
        )}
        <div className="seg layout" role="group" aria-label="View">
          <button aria-pressed={layout === 'single'} onClick={() => setLayout('single')}>Your feed</button>
          <button aria-pressed={layout === 'wall'} onClick={() => setLayout('wall')}>Gallery</button>
        </div>
        <div className={`live ${snap.connected ? '' : 'live-off'}`}>{snap.connected ? 'Live' : 'Offline'}</div>
      </header>
      <main>
        <div className={layout === 'wall' ? 'gallery-grid' : ''}>
          <Stage
            feed={feed} snap={snap} layout={layout} selected={selected} onSelect={setSelected}
            sound={sound} tactical={tactical} showStats={showStats}
          />
          {layout === 'wall' && <Talkback snap={snap} />}
        </div>
        <Controls
          feed={feed} snap={snap} tactical={tactical} onTactical={setTactical} showStats={showStats} onStats={setShowStats}
          selected={selected} onSelect={setSelected} sound={sound} onSound={setSound} layout={layout}
        />
        <AskBox feed={feed} snap={snap} selected={selected} />
      </main>
    </div>
  )
}
