import React from 'react';

export function classifyDiffLine(line) {
  if (line.startsWith('+++') || line.startsWith('---')) return 'diff-meta';
  if (line.startsWith('+')) return 'diff-add';
  if (line.startsWith('-')) return 'diff-del';
  if (line.startsWith('@@')) return 'diff-hunk';
  if (line.startsWith('diff ') || line.startsWith('index ')) return 'diff-meta';
  return '';
}

export default function DiffView({ diff }) {
  const lines = diff.split('\n');
  return (
    <div className="diff-view">
      {lines.map((line, i) => (
        <div key={i} className={`diff-line ${classifyDiffLine(line)}`}>{line || ' '}</div>
      ))}
    </div>
  );
}
