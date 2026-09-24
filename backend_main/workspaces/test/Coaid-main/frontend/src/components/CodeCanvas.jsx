import React, { useCallback, useEffect, useState } from 'react';
import DiffView from './DiffView';

function fmtTime(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleString([], {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export default function CodeCanvas({ open, file, files, onClose, fetchVersions, fetchContent }) {
  const [selectedFile, setSelectedFile] = useState(file);
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [viewMode, setViewMode] = useState('diff'); // 'diff' | 'full'
  const [fullContent, setFullContent] = useState(null);
  const [fullLoading, setFullLoading] = useState(false);

  useEffect(() => { if (open) setSelectedFile(file); }, [open, file]);

  const loadVersions = useCallback(async (f) => {
    if (!f) return;
    setLoading(true);
    try {
      const list = await fetchVersions(f);
      setVersions(list);
      setSelectedIndex(0);
      setViewMode('diff');
      setFullContent(null);
    } finally {
      setLoading(false);
    }
  }, [fetchVersions]);

  useEffect(() => {
    if (open && selectedFile) loadVersions(selectedFile);
  }, [open, selectedFile, loadVersions]);

  useEffect(() => {
    if (viewMode !== 'full' || !versions[selectedIndex]) return;
    setFullLoading(true);
    fetchContent(selectedFile, versions[selectedIndex].hash)
      .then(setFullContent)
      .catch(() => setFullContent('Could not load this snapshot.'))
      .finally(() => setFullLoading(false));
  }, [viewMode, selectedIndex, versions, selectedFile, fetchContent]);

  if (!open) return null;

  const current = versions[selectedIndex];

  return (
    <div className="palette-overlay" onClick={onClose}>
      <div className="canvas-modal" onClick={(e) => e.stopPropagation()}>
        <div className="canvas-header">
          <div className="canvas-title">
            <span className="canvas-icon">◪</span> Code Canvas
          </div>
          {files && files.length > 1 && (
            <select
              className="canvas-file-select"
              value={selectedFile || ''}
              onChange={(e) => setSelectedFile(e.target.value)}
            >
              {files.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          )}
          <div className="topbar-spacer" />
          <button className="mini" onClick={onClose}>✕</button>
        </div>

        <div className="canvas-body">
          <div className="canvas-versions">
            <div className="canvas-versions-label">{selectedFile}</div>
            {loading && <div className="empty">Loading versions…</div>}
            {!loading && versions.length === 0 && <div className="empty">No versions recorded this session.</div>}
            <ul className="canvas-version-list">
              {versions.map((v, i) => (
                <li key={v.hash}>
                  <button
                    className={i === selectedIndex ? 'active' : ''}
                    onClick={() => setSelectedIndex(i)}
                    type="button"
                  >
                    <span className="canvas-version-index">{versions.length - i}</span>
                    <div>
                      <div className="canvas-version-subject">{v.subject}</div>
                      <div className="canvas-version-meta mono dim small">{v.shortHash} · {fmtTime(v.timestamp)}</div>
                    </div>
                  </button>
                </li>
              ))}
              <li className="canvas-origin">
                <button className="disabled" type="button" disabled>
                  <span className="canvas-version-index">0</span>
                  <div><div className="canvas-version-subject dim">Session start</div></div>
                </button>
              </li>
            </ul>
          </div>

          <div className="canvas-main">
            {current && (
              <div className="canvas-view-toggle">
                <button className={viewMode === 'diff' ? 'active' : ''} onClick={() => setViewMode('diff')} type="button">Diff</button>
                <button className={viewMode === 'full' ? 'active' : ''} onClick={() => setViewMode('full')} type="button">Full file</button>
              </div>
            )}
            {!current && <div className="empty canvas-empty">Select a version to view its changes.</div>}
            {current && viewMode === 'diff' && <DiffView diff={current.diff} />}
            {current && viewMode === 'full' && (
              fullLoading
                ? <div className="empty canvas-empty">Loading snapshot…</div>
                : <pre className="canvas-full-content mono">{fullContent}</pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
