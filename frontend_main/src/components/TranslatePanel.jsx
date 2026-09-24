import { useCallback, useEffect, useRef, useState } from 'react'
import { getTranslateLanguages, getTranslateModels, translateText, extractErrorMessage } from '../api/client'
import OfficeDocTranslatePanel from './OfficeDocTranslatePanel'
import ImageTranslatePanel from './ImageTranslatePanel'

const DEBOUNCE_MS = 800
const MAX_RECENT = 5

const SUBTABS = [
  { id: 'text', label: 'Understand Text', icon: '🔤' },
  { id: 'image', label: 'Understand Image', icon: '🖼️' },
  { id: 'documents', label: 'Understand Document', icon: '📁' },
]

const DOC_TYPES = [
  {
    id: 'pptx', extension: '.pptx', label: 'PowerPoint',
    title: 'Understand a PowerPoint (.pptx)',
    statLabels: r => `${r.slides} slide${r.slides === 1 ? '' : 's'}, ${r.text_runs_translated} text run${r.text_runs_translated === 1 ? '' : 's'} translated${r.images_found > 0 ? `, ${r.images_translated}/${r.images_found} image${r.images_found === 1 ? '' : 's'} had text translated` : ''}.`,
  },
  {
    id: 'docx', extension: '.docx', label: 'Word',
    title: 'Understand a Word Document (.docx)',
    statLabels: r => `${r.parts_translated} part${r.parts_translated === 1 ? '' : 's'} (body/header/footer/notes), ${r.text_runs_translated} text run${r.text_runs_translated === 1 ? '' : 's'} translated${r.images_found > 0 ? `, ${r.images_translated}/${r.images_found} image${r.images_found === 1 ? '' : 's'} had text translated` : ''}.`,
  },
  {
    id: 'xlsx', extension: '.xlsx', label: 'Excel',
    title: 'Understand an Excel Workbook (.xlsx)',
    statLabels: r => `${r.worksheets} sheet${r.worksheets === 1 ? '' : 's'}, ${r.cells_with_text} cell${r.cells_with_text === 1 ? '' : 's'} with text, ${r.comment_parts} comment part(s), ${r.charts_translated} chart(s) translated${r.images_found > 0 ? `, ${r.images_translated}/${r.images_found} image${r.images_found === 1 ? '' : 's'} had text translated` : ''}.`,
  },
]

function fmtSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(0)}MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)}GB`
}

export default function TranslatePanel({ workspace, attached, onFilesChanged }) {
  const [languages, setLanguages] = useState({ source_languages: [], target_languages: [] })
  const [models, setModels] = useState([])
  const [model, setModel] = useState('')

  const [subTab, setSubTab] = useState('text')
  const [docType, setDocType] = useState('pptx')

  const [sourceLang, setSourceLang] = useState('auto')
  const [targetLang, setTargetLang] = useState('en')
  const [sourceText, setSourceText] = useState('')
  const [translatedText, setTranslatedText] = useState('')
  const [detectedName, setDetectedName] = useState(null)
  const [detectedCode, setDetectedCode] = useState(null)

  const [liveTranslate, setLiveTranslate] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(null) // 'source' | 'target' | null
  const [recent, setRecent] = useState([])

  // Guards against a slow, now-stale response (e.g. from before a swap or a
  // fast retype) overwriting newer state - the fix for "swap should be
  // error-less regardless of what's mid-flight".
  const requestIdRef = useRef(0)
  const debounceRef = useRef(null)
  const copyTimeoutRef = useRef(null)

  useEffect(() => {
    getTranslateLanguages().then(setLanguages).catch(() => {})
    getTranslateModels().then(res => {
      setModels(res.models)
      setModel(res.default_model || res.models?.[0]?.name || '')
    }).catch(() => {})
  }, [])

  const runTranslate = useCallback(async (text, srcLang, tgtLang, useModel) => {
    const trimmed = text.trim()
    if (!trimmed) {
      setTranslatedText('')
      setDetectedName(null)
      setDetectedCode(null)
      setError(null)
      return
    }
    const myRequestId = ++requestIdRef.current
    setLoading(true)
    setError(null)
    try {
      const res = await translateText(trimmed, srcLang, tgtLang, useModel)
      if (myRequestId !== requestIdRef.current) return // a newer request/edit/swap superseded this one
      setTranslatedText(res.translation)
      setDetectedName(res.detected_source_lang || null)
      setDetectedCode(res.detected_source_code || null)
      setRecent(prev => {
        const entry = { sourceText: trimmed, translatedText: res.translation, sourceLang: srcLang, targetLang: tgtLang }
        const withoutDup = prev.filter(r => r.sourceText !== trimmed || r.targetLang !== tgtLang)
        return [entry, ...withoutDup].slice(0, MAX_RECENT)
      })
    } catch (e) {
      if (myRequestId !== requestIdRef.current) return
      setError(extractErrorMessage(e))
    } finally {
      if (myRequestId === requestIdRef.current) setLoading(false)
    }
  }, [])

  // Live (debounced) translate as you type/change languages/model.
  useEffect(() => {
    if (!liveTranslate) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      runTranslate(sourceText, sourceLang, targetLang, model)
    }, DEBOUNCE_MS)
    return () => clearTimeout(debounceRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceText, sourceLang, targetLang, model, liveTranslate])

  const handleManualTranslate = () => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    runTranslate(sourceText, sourceLang, targetLang, model)
  }

  const handleKeyDown = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      handleManualTranslate()
    }
  }

  // The swap that stays valid no matter what state we're in: before any
  // translation has run, mid-request, or after a completed one. Never
  // produces "auto" as the target (which the model has no dropdown entry
  // for), and always falls back sensibly if a source language was never
  // actually detected yet.
  const handleSwap = () => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    requestIdRef.current++ // invalidate any in-flight request from before the swap

    const newSourceLang = targetLang
    const newTargetLang = sourceLang === 'auto' ? (detectedCode || 'en') : sourceLang

    setSourceLang(newSourceLang)
    setTargetLang(newTargetLang)
    setSourceText(translatedText)
    setTranslatedText(sourceText)
    setDetectedName(null)
    setDetectedCode(null)
    setError(null)
    setLoading(false)
  }

  const handleClear = () => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    requestIdRef.current++
    setSourceText('')
    setTranslatedText('')
    setDetectedName(null)
    setDetectedCode(null)
    setError(null)
    setLoading(false)
  }

  const handleCopy = async (which, text) => {
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setCopied(which)
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current)
      copyTimeoutRef.current = setTimeout(() => setCopied(null), 1500)
    } catch {
      // clipboard API unavailable/blocked - fail silently, nothing to break
    }
  }

  const restoreRecent = (entry) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    requestIdRef.current++
    setSourceLang(entry.sourceLang)
    setTargetLang(entry.targetLang)
    setSourceText(entry.sourceText)
    setTranslatedText(entry.translatedText)
    setDetectedName(null)
    setDetectedCode(null)
    setError(null)
  }

  const targetLangName = languages.target_languages.find(l => l.code === targetLang)?.name || targetLang
  const activeDocType = DOC_TYPES.find(d => d.id === docType)

  return (
    <div className="translate-shell">
      <div className="subtab-group">
        {SUBTABS.map(t => (
          <button
            key={t.id}
            className={`subtab-btn ${subTab === t.id ? 'active' : ''}`}
            onClick={() => setSubTab(t.id)}
          >
            <span className="subtab-icon">{t.icon}</span>{t.label}
          </button>
        ))}
      </div>

      {/* Every sub-section below is CSS-hidden (not unmounted) when
          inactive, same persistence model as the app's top-level tabs -
          switching between Text/Image/Documents, or between doc types
          within Documents, never loses typed text or in-progress results. */}

      <div style={{ display: subTab === 'text' ? 'block' : 'none' }}>
        <div className="panel">
          <h3>Understand Text</h3>
          

          <div className="lang-swap-row" style={{ marginTop: 12 }}>
            <select className="select" value={sourceLang} onChange={e => setSourceLang(e.target.value)}>
              {languages.source_languages.map(l => (
                <option key={l.code} value={l.code}>{l.name}</option>
              ))}
            </select>

            <button className="btn small" onClick={handleSwap} title="Swap languages and text">⇄</button>

            <select className="select" value={targetLang} onChange={e => setTargetLang(e.target.value)}>
              {languages.target_languages.map(l => (
                <option key={l.code} value={l.code}>{l.name}</option>
              ))}
            </select>
          </div>

          <div className="grid-2" style={{ marginTop: 10 }}>
            <div>
              <textarea
                className="input"
                placeholder="Type or paste text to understand for…"
                value={sourceText}
                onChange={e => setSourceText(e.target.value)}
                onKeyDown={handleKeyDown}
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                <span className="issue-meta">
                  {sourceText.length} character{sourceText.length === 1 ? '' : 's'}
                  {sourceLang === 'auto' && detectedName && ` · Detected: ${detectedName}`}
                </span>
                <span style={{ display: 'flex', gap: 8 }}>
                  <button className="btn small ghost" onClick={handleClear} disabled={!sourceText && !translatedText}>Clear</button>
                  <button className="btn small ghost" onClick={() => handleCopy('source', sourceText)} disabled={!sourceText}>
                    {copied === 'source' ? 'Copied!' : 'Copy'}
                  </button>
                </span>
              </div>
            </div>

            <div>
              <textarea
                className="input"
                style={{ background: '#fafafe' }}
                placeholder=""
                value={translatedText}
                readOnly
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                <span className="issue-meta">
                  {loading ? <><span className="spinner" /> Translating…</> : `${translatedText.length} character${translatedText.length === 1 ? '' : 's'}`}
                </span>
                <button className="btn small ghost" onClick={() => handleCopy('target', translatedText)} disabled={!translatedText}>
                  {copied === 'target' ? 'Copied!' : 'Copy'}
                </button>
              </div>
            </div>
          </div>

          <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <button className="btn primary" onClick={handleManualTranslate} disabled={loading || !sourceText.trim()}>
              {loading ? <><span className="spinner" /> Translating…</> : `Translate to ${targetLangName}`}
            </button>
            <span className="hint" style={{ margin: 0 }}>
              {liveTranslate ? 'Live understanding is on' : 'Live understanding is off'}
            </span>
          </div>

          {error && <div className="hint" style={{ color: 'var(--err)', marginTop: 8 }}>{error}</div>}

          <div className="translate-toolbar">
            <div className="field">
              <span className="field-label">Model</span>
              <select className="select" value={model} onChange={e => setModel(e.target.value)}>
                {models.map(m => (
                  <option key={m.name} value={m.name}>
                    {m.name}{m.size_bytes ? ` (${fmtSize(m.size_bytes)})` : ''}
                  </option>
                ))}
              </select>
            </div>
            <label className="switch-field">
              <input type="checkbox" checked={liveTranslate} onChange={e => setLiveTranslate(e.target.checked)} />
              Live Understanding
            </label>
          </div>
        </div>

        {recent.length > 0 && (
          <div className="panel" style={{ marginTop: 16 }}>
            <h3>Recent</h3>
            {recent.map((r, idx) => (
              <div
                key={idx}
                className="issue-row"
                style={{ cursor: 'pointer' }}
                onClick={() => restoreRecent(r)}
                title="Click to restore"
              >
                <div className="issue-main">
                  <div className="issue-msg" style={{ fontSize: 12.5 }}>
                    {r.sourceText.length > 80 ? r.sourceText.slice(0, 80) + '…' : r.sourceText}
                  </div>
                  <div className="issue-meta">
                    → {r.translatedText.length > 80 ? r.translatedText.slice(0, 80) + '…' : r.translatedText}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: subTab === 'image' ? 'block' : 'none' }}>
        <ImageTranslatePanel languages={languages} />
      </div>

      <div style={{ display: subTab === 'documents' ? 'block' : 'none' }}>
        <div className="doctype-group">
          {DOC_TYPES.map(d => (
            <button
              key={d.id}
              className={`doctype-btn ${docType === d.id ? 'active' : ''}`}
              onClick={() => setDocType(d.id)}
            >
              <span className="dot" />{d.label}
            </button>
          ))}
        </div>

        {DOC_TYPES.map(d => (
          <div key={d.id} style={{ display: docType === d.id ? 'block' : 'none' }}>
            <OfficeDocTranslatePanel
              kind={d.id} extension={d.extension} title={d.title} description={d.description}
              statLabels={d.statLabels}
              workspace={workspace} attached={attached} languages={languages} models={models}
              defaultModel={model} onFilesChanged={onFilesChanged}
            />
          </div>
        ))}
      </div>
    </div>
  )
}