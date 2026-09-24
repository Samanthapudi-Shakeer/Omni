import diffKitHtml from '../assets/diffkit.html?raw'

// diffkit is a fully self-contained tool (its own dark-themed CSS, its own
// vanilla-JS Myers diff engine, drag/drop file loading via FileReader,
// canvas minimap, and PDF/image/.diff export) - it needs no data from the
// rest of this app and never sends anything anywhere (files are read and
// compared entirely client-side). A sandboxed iframe is the right way to
// host it: it can't touch this app's DOM/state, and this app's styles
// can't leak into it either, so its own dark theme always renders exactly
// as designed regardless of what else changes here.
export default function DiffKitPanel() {
  return (
    <div className="panel diffkit-panel">
      
    
      <iframe
        title="Diff Kit"
        className="diffkit-frame"
        srcDoc={diffKitHtml}
        sandbox="allow-scripts allow-downloads allow-modals"
      />
    </div>
  )
}
