import React, { useEffect, useRef, useState } from 'react';
import { apiGet, apiPost } from '../api';
import TerminalView from './TerminalView';
import Composer from './Composer';

const FALLBACK_PHASE = 'Preparing isolated Aider session';
function decode(raw = []) { try { return raw.map((value) => { const bin = atob(value); return Uint8Array.from(bin, (c) => c.charCodeAt(0)); }); } catch (_) { return []; } }

/** A real, persisted Aider terminal for a modularize/testgen task session. */
export default function ToolTaskProgress({ running, statusPath, terminalEnabled = false }) {
  const [status, setStatus] = useState(null);
  const [answer, setAnswer] = useState('');
  const [input, setInput] = useState('');
  const writeRef = useRef(null);
  const seenRef = useRef(0);
  const initialRef = useRef([]);

  useEffect(() => {
    if (!running) return undefined;
    let cancelled = false;
    const refresh = async () => {
      try {
        const next = await apiGet(statusPath);
        const chunks = decode(next.raw);
        if (!seenRef.current) initialRef.current = chunks;
        else chunks.slice(seenRef.current).forEach((chunk) => writeRef.current?.(chunk));
        seenRef.current = chunks.length;
        if (!cancelled) setStatus(next);
      } catch (_) { /* the main task request reports actionable failures */ }
    };
    seenRef.current = 0; initialRef.current = []; setStatus(null); refresh();
    const timer = setInterval(refresh, 1000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [running, statusPath]);

  if (!running) return null;
  const phases = status?.phaseTimeline || [];
  const current = phases.at(-1)?.label || FALLBACK_PHASE;
  const question = status?.pendingQuestion;
  const endpoint = (action) => statusPath.replace('/status', `/${action}`);
  const send = async (action, payload = {}) => { await apiPost(endpoint(action), payload); };
  const answerQuestion = async (value) => { if (value.trim()) { await send('answer', { text: value }); setAnswer(''); } };
  return <section className="tool-progress" aria-live="polite">
    <div className="tool-progress-current"><span className="spinner" /> {current}</div>
    <div className="tool-progress-phases">{phases.length === 0 ? <span>Starting Aider…</span> : phases.map((phase, index) => <span key={`${phase.label}-${phase.at}`} className={index === phases.length - 1 ? 'active' : ''}>✓ {phase.label}</span>)}</div>
    {question && <div className="tool-human-question"><strong>Aider needs your answer:</strong> {question.question || 'Continue?'}<div>{(question.options || [{ key: 'Y', label: 'Y' }, { key: 'N', label: 'N' }]).map((o) => <button className="btn small" key={o.key} onClick={() => answerQuestion(o.key)}>{o.label}</button>)}</div><div className="tool-answer"><input value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Type Y/N or another answer" /><button className="btn small primary" onClick={() => answerQuestion(answer)}>Send</button></div></div>}
    {terminalEnabled && <div className="tool-aider-console"><div className="tool-terminal-toolbar"><strong>Dedicated Aider terminal</strong><span>Files are attached and your task prompt was sent.</span><button className="btn small" onClick={() => send('clear')}>Clear</button><button className="btn small" onClick={() => send('tokens')}>Tokens</button></div><TerminalView onWriteRef={writeRef} initialChunks={initialRef.current} onData={(data) => send('raw', { data: btoa(data) })} /><Composer value={input} onChange={setInput} onSend={(text) => { send('prompt', { text }); setInput(''); }} disabled={false} statusLabel={status?.status} /></div>}
  </section>;
}
