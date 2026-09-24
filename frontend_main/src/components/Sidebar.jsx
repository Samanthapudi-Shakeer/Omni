import { useRef } from 'react'
import { useState } from 'react'
import { uploadFile, uploadZip, extractErrorMessage } from '../api/client'

function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

export default function Sidebar({
  workspace, setWorkspace,
  files, refreshFiles,
  attached, toggleAttach, clearAttached, onShowHistory, onDelete,
}) {
  const fileInputRef = useRef(null)
  const [uploadError, setUploadError] = useState('')
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState({})

  const tree = (() => {
    const root = { dirs: {}, files: [] }
    files.filter(f => f.name.toLowerCase().includes(query.toLowerCase())).forEach(file => {
      const parts = file.name.split('/')
      let node = root
      parts.slice(0, -1).forEach(part => { node.dirs[part] ||= { dirs: {}, files: [] }; node = node.dirs[part] })
      node.files.push(file)
    })
    return root
  })()

  const renderTree = (node, prefix = '') => (
    <>
      {Object.entries(node.dirs).sort(([a], [b]) => a.localeCompare(b)).map(([name, child]) => {
        const path = `${prefix}${name}/`
        const open = expanded[path] !== false
        return <div key={path}>
          <button className="tree-folder" onClick={() => setExpanded(p => ({ ...p, [path]: !open }))}>
            <span>{open ? '▾' : '▸'}</span> {name}
          </button>
          {open && <div className="tree-children">{renderTree(child, path)}</div>}
        </div>
      })}
      {node.files.sort((a, b) => a.name.localeCompare(b.name)).map(f => (
        <div className="file-row" key={f.name}>
          <input type="checkbox" checked={!!attached.find(a => a.name === f.name)} onChange={() => toggleAttach(f)} />
          <span className="file-name" title={f.name}>📄 {f.name.split('/').pop()}</span>
          <span className="file-size">{fmtSize(f.size_bytes)}</span>
          <button className="file-action" title="View history" onClick={() => onShowHistory?.(f.name)}>↺</button>
          <button className="file-action danger-text" title="Delete file" onClick={() => onDelete?.(f)}>×</button>
        </div>
      ))}
    </>
  )

  const handleUpload = async (e) => {
    const picked = e.target.files
    if (!picked?.length) return
    setUploadError('')
    try {
      for (const f of picked) {
        if (f.name.toLowerCase().endsWith('.zip')) await uploadZip(workspace, f)
        else await uploadFile(workspace, f)
      }
      refreshFiles()
    } catch (error) {
      setUploadError(`Upload failed: ${extractErrorMessage(error)}`)
    } finally {
      e.target.value = ''
    }
  }

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-dot" />
        <div>
          <div className="brand-title">OmniZen AI</div>
        </div>
      </div>

      <div className="section-label">WORKSPACE</div>
      <select className="select" style={{ width: '100%' }} value={workspace}
        onChange={e => setWorkspace(e.target.value)}>
        <option value="test">test</option>
      </select>

      <div className="section-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span>WORKSPACE FILES</span>
        <span>
          <button className="btn small ghost" onClick={refreshFiles}>Refresh</button>{' '}
          <button className="btn small ghost" onClick={() => fileInputRef.current?.click()}>Upload</button>
          <input ref={fileInputRef} type="file" multiple hidden onChange={handleUpload} />
        </span>
      </div>
      {uploadError && <div className="error">{uploadError}</div>}
      <input className="input file-search" placeholder="Search files…" value={query} onChange={e => setQuery(e.target.value)} />
      <div className="file-list">
        {files.length === 0 && <div className="empty-state">No files yet</div>}
        {files.length > 0 && Object.keys(tree.dirs).length === 0 && tree.files.length === 0
          ? <div className="empty-state">No matching files</div> : renderTree(tree)}
      </div>

      <div className="section-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span>ATTACHED</span>
        <span className="badge">{attached.length} file{attached.length === 1 ? '' : 's'}</span>
      </div>
      <div className="attached-box">
        {attached.length === 0 && 'Nothing attached yet.'}
        {attached.map(f => (
          <span className="attached-chip" key={f.name}>
            {f.name}
            <button onClick={() => toggleAttach(f)}>×</button>
          </span>
        ))}
        {attached.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <button className="btn small ghost" onClick={clearAttached}>Clear all</button>
          </div>
        )}
      </div>
    </aside>
  )
}
