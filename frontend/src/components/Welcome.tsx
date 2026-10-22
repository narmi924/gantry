/** What a first-time visitor sees over the moving picture: what this is, and one click to the best part with sound. */
export function Welcome({ onWatch, onStart }: { onWatch: () => void; onStart: () => void }) {
  return (
    <div className="welcome" role="dialog" aria-modal="false" aria-labelledby="welcome-title">
      <div className="welcome-card">
        <h1 id="welcome-title" className="welcome-title">
          One match. One AI production crew.
          <br />
          A different broadcast for every fan.
        </h1>
        <p className="welcome-body">
          A synthetic football match, covered live by a crew of AI agents that makes four broadcasts at once: for
          a new fan, for an analyst, for a Kingsmere fan following their No. 10, and for blind and partially sighted
          fans. Each feed has its own commentary, voice, camera and graphics. Any feed can be made in eight languages.
        </p>
        <div className="welcome-actions">
          <button className="welcome-go" onClick={onWatch} autoFocus>
            Watch the first goal, with sound
          </button>
          <button className="welcome-start" onClick={onStart}>
            Start from kick-off
          </button>
        </div>
      </div>
    </div>
  )
}
