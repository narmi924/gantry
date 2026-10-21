import { useEffect, useRef, useState } from 'react'
import type { FeedSnapshot, MatchFeed } from '../feed'
import { t } from '../i18n'
import { AUDIENCE_LABEL, audienceOf, type Audience, type FeedId } from '../types'

/** Questions a first-time viewer can ask with one click, per audience. */
const SUGGEST: Record<Audience, string[]> = {
  casual: ['Why are Kingsmere on top?', 'Who has been the best player so far?'],
  analyst: ['How did the first goal come about?', 'Which team is pressing better?'],
  home: ['How is Aldana playing today?', 'How far has Aldana run?'],
  audio: ['Where is the ball right now?', 'What is the score, and who is on top?'],
}

const PROMPT: Record<Audience, string> = {
  casual: 'Ask your broadcast, e.g. “Why are Kingsmere on top?”',
  analyst: 'Ask the analyst, e.g. “How did the first goal come about?”',
  home: 'Ask about Aldana, e.g. “How far has he run today?”',
  audio: 'Ask a question about the match, or press V and speak',
}

/** Where a viewer asks their own broadcast a question, by typing or by voice. */
export function AskBox({ feed, snap, selected }: { feed: MatchFeed; snap: FeedSnapshot; selected: FeedId }) {
  const [text, setText] = useState('')
  const [listening, setListening] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const busy = snap.asking !== null
  const info = snap.feeds.find((f) => f.id === selected)
  const label = info?.name ?? AUDIENCE_LABEL[audienceOf(selected)]
  // a viewer's own feed asks about the player they follow
  const followed = info?.custom && info.follow ? snap.meta?.teams.flatMap((t) => t.players).find((p) => p.id === info.follow) : undefined
  const prompt = followed ? `Ask about ${followed.last}, e.g. “How fast has he been today?”` : PROMPT[audienceOf(selected)]
  const suggestions = followed ? [`How is ${followed.last} playing today?`, `What is ${followed.last}'s top speed?`] : SUGGEST[audienceOf(selected)]
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
      const res = await fetch(`/api/speech-token?ticket=${encodeURIComponent(snap.ticket ?? '')}`)
      if (!res.ok) throw new Error('token')
      const { token, region } = await res.json()
      const sdk = await import('microsoft-cognitiveservices-speech-sdk')
      const cfg = sdk.SpeechConfig.fromAuthorizationToken(token, region)
      // the feed listens in its own language
      cfg.speechRecognitionLanguage = info?.locale ?? 'en-GB'
      const rec = new sdk.SpeechRecognizer(cfg, sdk.AudioConfig.fromDefaultMicrophoneInput())
      rec.recognizing = (_s, e) => setText(e.result.text)
      rec.recognizeOnceAsync(
        (r) => {
          rec.close()
          setListening(false)
          const q = r.text?.trim().replace(/[.\u3002]$/, '')
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
    <>
    <form className="ask" onSubmit={submit}>
      <label className="ask-label" htmlFor="ask-input">Ask {label}</label>
      <input
        id="ask-input"
        className="ask-input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={listening ? 'Listening…' : prompt}
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
    <div className="suggest" role="group" aria-label="Suggested questions">
      {suggestions.map((q) => (
        <button key={q} type="button" disabled={busy} onClick={() => feed.ask(selected, q)}>{q}</button>
      ))}
    </div>
    </>
  )
}

/** On the picture: the question being answered, so the replay and the voice make sense. */
export function QuestionCard({ snap, feedId, lang }: { snap: FeedSnapshot; feedId: FeedId; lang: string }) {
  const recent = snap.answer?.feed === feedId && performance.now() - snap.answer.at < 20000
  const q = snap.asking?.feed === feedId ? snap.asking.question : recent ? snap.answer!.question : null
  if (!q) return null
  return (
    <div className="qcard" key={q}>
      <span className="qcard-label">{t(lang, 'you_asked')}</span>
      <span className="qcard-text">{q}</span>
    </div>
  )
}
