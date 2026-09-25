import React, { useEffect, useRef } from 'react';

export default function OutputPane({ lines }) {
  const ref = useRef(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.scrollTop = ref.current.scrollHeight;
    }
  }, [lines]);

  return (
    <div className="output" ref={ref}>
      {lines.map((line, i) => (
        <span key={i} className={line.cls || undefined}>{line.text}</span>
      ))}
    </div>
  );
}
