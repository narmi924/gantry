import { useEffect, useRef, useState } from 'react'
import type { FeedSnapshot, MatchFeed } from '../feed'
import { FEEDS, type FeedId } from '../types'

const PROMPT: Record<FeedId, string> = {
  casual_en: 'Ask your broadcast, e.g. “Why are Kingsmere on top?”',
  analyst_en: 'Ask the analyst, e.g. “How did the first goal come about?”',
  home_zh: '问问你的转播，比如“Aldana 今天跑了多少？”',
  audio_en: 'Ask a question about the match, or press V and speak',
}

/** The language each feed listens in when a viewer speaks a question. */
const LISTEN: Record<FeedId, string> = { casual_en: 'en-GB', analyst_en: 'en-US', home_zh: 'zh-CN', audio_en: 'en-GB' }

/** Where a viewer asks their own broadcast a question, by typing or by voice. */
export function AskBox({ feed, snap, selected }: { feed: MatchFeed; snap: FeedSnapshot; selected: FeedId }) {
  const [text, setText] = useState('')
  const [listening, setListening] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const busy = snap.asking !== null
  const label = FEEDS.find((f) => f.id === selected)?.label
  const listenRef = useRef<() => void>(() => {})

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const q = text.trim()
    if (!q || busy) return
    feed.ask(selected, q)
    setText('')
  }

  // Azure AI Speech turns the spoken question into text in the feed's language
  const listen = async () => {
    if (listening || busy) return
    setProblem(null)
    setListening(true)
    try {
      const res = await fetch('/api/speech-token')
      if (!res.ok) throw new Error('token')
      const { token, region } = await res.json()
      const sdk = await import('microsoft-cognitiveservices-speech-sdk')
      const cfg = sdk.SpeechConfig.fromAuthorizationToken(token, region)
      cfg.speechRecognitionLanguage = LISTEN[selected]
      const rec = new sdk.SpeechRecognizer(cfg, sdk.AudioConfig.fromDefaultMicrophoneInput())
      rec.recognizing = (_s, e) => setText(e.result.text)
      rec.recognizeOnceAsync(
        (r) => {
          rec.close()
          setListening(false)
          const q = r.text?.trim().replace(/[。.]$/, '')
          if (q) {
            setText('')
            feed.ask(selected, q)
          } else setProblem('Didn’t catch that. Try again, or type your question.')
        },
        () => {
          rec.close()
          setListening(false)
          setProblem('The microphone isn’t available. You can type your question instead.')
        },
      )
    } catch {
      setListening(false)
      setProblem('Voice questions aren’t available right now. You can type your question instead.')
    }
  }
  listenRef.current = listen

  // V asks by voice from anywhere on the page, for viewers who can't see the box
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === 'v') listenRef.current()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <form className="ask" onSubmit={submit}>
      <label className="ask-label" htmlFor="ask-input">Ask {label}</label>
      <input
        id="ask-input"
        className={`ask-input ${selected === 'home_zh' ? 'ask-zh' : ''}`}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={listening ? (selected === 'home_zh' ? '请说…' : 'Listening…') : PROMPT[selected]}
        autoComplete="off"
      />
      {problem && <span className="ask-problem" role="status">{problem}</span>}
      <button type="button" className={`mic ${listening ? 'mic-on' : ''}`} onClick={listen} aria-label="Ask by voice (V)" disabled={busy}>
        <svg viewBox="0 0 24 24" aria-hidden>
          <rect x="9" y="3" width="6" height="11" rx="3" />
          <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" fill="none" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>
      <button className="ask-btn" type="submit" disabled={busy || !text.trim()}>
        {busy ? 'The crew is on it…' : 'Ask'}
      </button>
    </form>
  )
}

/** On the picture: the question being answered, so the replay and the voice make sense. */
export function QuestionCard({ snap, feedId }: { snap: FeedSnapshot; feedId: FeedId }) {
  const recent = snap.answer?.feed === feedId && performance.now() - snap.answer.at < 20000
  const q = snap.asking?.feed === feedId ? snap.asking.question : recent ? snap.answer!.question : null
  if (!q) return null
  const zh = feedId === 'home_zh'
  return (
    <div className={`qcard ${zh ? 'qcard-zh' : ''}`} key={q}>
      <span className="qcard-label">{zh ? '你的问题' : 'You asked'}</span>
      <span className="qcard-text">{q}</span>
    </div>
  )
}
