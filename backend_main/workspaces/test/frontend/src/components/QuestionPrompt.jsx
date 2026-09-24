import React, { useState } from 'react';

export default function QuestionPrompt({ question, onAnswer }) {
  const [answerText, setAnswerText] = useState('');

  function submit(e) {
    e.preventDefault();
    if (!answerText.trim()) return;
    onAnswer(answerText.trim());
    setAnswerText('');
  }

  return (
    <div className="question-card">
      <div className="question-text">{question.question}</div>
      {question.options.length > 0 && (
        <div className="question-options">
          {question.options.map((o) => (
            <button key={o.key} className="btn small primary" type="button" onClick={() => onAnswer(o.label)}>
              {o.label}
            </button>
          ))}
        </div>
      )}
      <form className="question-freeform" onSubmit={submit}>
        <input
          type="text"
          placeholder="Or type a custom response…"
          value={answerText}
          onChange={(e) => setAnswerText(e.target.value)}
        />
        <button className="btn small" type="submit">Send</button>
      </form>
    </div>
  );
}
