import { useEffect, useState } from 'react'
import { getFileHistory, getFileDiff } from '../api/client'

export default function FileHistoryModal({ workspace, filename, onClose }) {
  const [commits, setCommits] = useState([])
  const [loading, setLoading] = useState(true)

  const [fromHash, setFromHash] = useState(null)
  const [toHash, setToHash] = useState('HEAD')

  const [diff, setDiff] = useState('')
  const [diffLoading, setDiffLoading] = useState(false)

  // ---------------------------------------------------------
  // Load file history
  // ---------------------------------------------------------

  useEffect(() => {
    if (!filename) return

    setLoading(true)
    setCommits([])
    setDiff('')
    setFromHash(null)
    setToHash('HEAD')

    getFileHistory(workspace, filename)
      .then(res => {
        const history = res?.commits || []

        setCommits(history)

        // Default "From" to the oldest commit/baseline
        if (history.length > 0) {
          setFromHash(history[history.length - 1].hash)
        } else {
          setFromHash(null)
        }
      })
      .catch(error => {
        console.error('Failed to load file history:', error)
        setCommits([])
        setFromHash(null)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [workspace, filename])

  // ---------------------------------------------------------
  // Load diff whenever From / To changes
  // ---------------------------------------------------------

  useEffect(() => {
    if (!filename || !fromHash) {
      setDiff('')
      return
    }

    setDiffLoading(true)

    const params = {
      from_ref: fromHash,
      to_ref: toHash,
    }

    getFileDiff(workspace, filename, params)
      .then(res => {
        setDiff(res?.diff || '')
      })
      .catch(error => {
        console.error('Failed to load file diff:', error)
        setDiff('')
      })
      .finally(() => {
        setDiffLoading(false)
      })
  }, [workspace, filename, fromHash, toHash])

  // ---------------------------------------------------------
  // Don't render without filename
  // ---------------------------------------------------------

  if (!filename) {
    return null
  }

  // ---------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------

  const formatCommitMessage = message => {
    if (!message) return 'No commit message'

    return message.replace(/^AI fix:\s*/i, '')
  }

  // ---------------------------------------------------------
  // Render
  // ---------------------------------------------------------

  return (
    <div
      className="modal-backdrop"
      onClick={onClose}
    >
      <div
        className="modal"
        style={{ width: 680 }}
        onClick={e => e.stopPropagation()}
      >
        {/* Close button */}

        <button
          className="modal-close"
          onClick={onClose}
          aria-label="Close"
        >
          ✕
        </button>

        {/* Title */}

        <h4>
          History — {filename}
        </h4>

        {/* Loading history */}

        {loading ? (
          <div className="empty-state">
            <span className="spinner" />
            Loading history…
          </div>
        ) : commits.length === 0 ? (

          /* No history */

          <div className="empty-state">
            No AI fixes applied to this file yet.
          </div>

        ) : (

          /* History available */

          <>
            {/* ------------------------------------------------
                Version comparison
            ------------------------------------------------ */}

            <div className="section-label">
              COMPARE TWO VERSIONS ({commits.length + 1} available)
            </div>

            <div className="history-selects">

              {/* FROM */}

              <label>
                From

                <select
                  className="select"
                  value={fromHash || ''}
                  onChange={e => {
                    setFromHash(
                      e.target.value || null
                    )
                  }}
                >

                  {/* Baseline */}

                  <option
                    value={
                      commits.length
                        ? commits[commits.length - 1].hash
                        : ''
                    }
                  >
                    Baseline
                  </option>

                  {/* Commits */}

                  {commits.map(commit => (
                    <option
                      key={commit.hash}
                      value={commit.hash}
                    >
                      {commit.short_hash} —{' '}
                      {formatCommitMessage(
                        commit.message
                      )}
                    </option>
                  ))}

                </select>
              </label>

              {/* Arrow */}

              <span className="history-arrow">
                →
              </span>

              {/* TO */}

              <label>
                To

                <select
                  className="select"
                  value={toHash}
                  onChange={e => {
                    setToHash(e.target.value)
                  }}
                >

                  {/* Current HEAD */}

                  <option value="HEAD">
                    Current
                  </option>

                  {/* Commits */}

                  {commits.map(commit => (
                    <option
                      key={commit.hash}
                      value={commit.hash}
                    >
                      {commit.short_hash} —{' '}
                      {formatCommitMessage(
                        commit.message
                      )}
                    </option>
                  ))}

                </select>
              </label>

            </div>

            {/* ------------------------------------------------
                Diff
            ------------------------------------------------ */}

            <div className="section-label">
              DIFF
            </div>

            {diffLoading ? (

              <div className="empty-state">
                <span className="spinner" />
                Loading diff…
              </div>

            ) : (

              <div className="diff-box">
                {diff || '(no changes)'}
              </div>

            )}

          </>
        )}
      </div>
    </div>
  )
}