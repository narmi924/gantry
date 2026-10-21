import { useEffect, useRef, useState } from 'react'
import { AskBox } from './components/AskBox'
import { Controls } from './components/Controls'
import { Stage, type Layout } from './components/Stage'
import { Talkback } from './components/Talkback'
import { Welcome } from './components/Welcome'
import { useCrowd } from './crowd'
import { BuildFeed } from './components/BuildFeed'
import { DEFAULT_FEEDS, FEED_ID, type FeedId } from './types'
import { useFeed } from './useFeed'

/** The feeds on air: the four default broadcasts, or any audiences and languages asked for with ?feeds= */
const ALL_FEEDS: FeedId[] = (() => {
  const asked = new URLSearchParams(location.search).get('feeds')
  const list = asked ? asked.split(',').filter((f) => FEED_ID.test(f)) : []
  return list.length ? list.slice(0, 6) : DEFAULT_FEEDS
})()

function initial() {
  const q = new URLSearchParams(location.search)
  const feed = (ALL_FEEDS.find((f) => f === q.get('feed')) ?? ALL_FEEDS[0]) as FeedId
  const layout: Layout = q.get('view') === 'wall' ? 'wall' : 'single'
  return { feed, layout }
}

export default function App() {
  const [feeds, setFeeds] = useState<FeedId[]>(ALL_FEEDS)
  const [building, setBuilding] = useState(false)
  const { feed, snap } = useFeed('demo', feeds)
  const [tactical, setTactical] = useState(false)
  const [showStats, setShowStats] = useState(false)
  const [selected, setSelected] = useState<FeedId>(() => initial().feed)
  const [layout, setLayout] = useState<Layout>(() => initial().layout)
  const [sound, setSound] = useState(false)
  // a first-time visitor gets one line on what this is and one click to the best part; links straight to a moment skip it
  const [welcome, setWelcome] = useState(() => !/[?&](t|minute|view|feed|skip)=/.test(location.search))
  const meta = snap.meta
  // behind the welcome, the match plays from the build-up to the first goal, silently
  const behindWelcome = useRef(false)
  useEffect(() => {
    const goal = snap.chapters.find((c) => c.kind === 'goal')
    if (!welcome || behindWelcome.current || !goal) return
    behindWelcome.current = true
    feed.seek(Math.max(0, goal.tick - 300))
  }, [welcome, snap.chapters, feed])
  const watchFirstGoal = () => {
    const goal = snap.chapters.find((c) => c.kind === 'goal')
    setWelcome(false)
    setLayout('wall')
    setSound(true)
    feed.setSpeed(1)
    feed.setPlaying(true)
    if (goal) feed.seek(goal.tick + 30)
  }
  const startFromKickoff = () => {
    setWelcome(false)
    setSound(true)
    feed.setPlaying(true)
    feed.seek(0)
  }
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
      else if (/^[1-9]$/.test(e.key) && feeds[Number(e.key) - 1]) setSelected(feeds[Number(e.key) - 1])
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [feed, feeds])

  const buildFeed = (id: FeedId) => {
    // the produced broadcasts stay; the viewer's own feed joins them on the wall
    setFeeds([...DEFAULT_FEEDS, id])
    setSelected(id)
    setLayout('wall')
    setSound(true)
    setBuilding(false)
    setWelcome(false)
  }

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
            feed={feed} snap={snap} layout={layout} feeds={feeds} selected={selected} onSelect={setSelected}
            sound={sound} tactical={tactical} showStats={showStats}
          />
          {layout === 'wall' && <Talkback feed={feed} snap={snap} />}
          {welcome && <Welcome onWatch={watchFirstGoal} onStart={startFromKickoff} />}
          {building && meta && <BuildFeed meta={meta} onBuild={buildFeed} onClose={() => setBuilding(false)} />}
        </div>
        <Controls
          feed={feed} snap={snap} tactical={tactical} onTactical={setTactical} showStats={showStats} onStats={setShowStats}
          selected={selected} onSelect={setSelected} sound={sound} onSound={setSound} layout={layout} feeds={feeds}
          onBuild={() => setBuilding(true)}
        />
        <AskBox feed={feed} snap={snap} selected={selected} />
      </main>
    </div>
  )
}
