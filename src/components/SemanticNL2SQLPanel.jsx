import { useState } from 'react';
import { motion as Motion, AnimatePresence } from 'framer-motion';
import {
  Sparkles,
  Send,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Database,
  Terminal,
  ShieldCheck,
  Zap,
  Info,
} from 'lucide-react';
import { nl2sqlQuery } from '../api/api';

const SAMPLE_QUERIES = [
  'How many surveys are there?',
  'How many survey responses are there?',
  'Which questions received the most answers?',
  'How many answers does each survey have?',
  'Which survey has the most responses?',
];

export default function SemanticNL2SQLPanel({ compact = false }) {
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [response, setResponse] = useState(null);
  const [copied, setCopied] = useState(false);
  const [showCorrection, setShowCorrection] = useState(true);
  const [showRetrieval, setShowRetrieval] = useState(false);

  async function handleSubmit(queryToRun) {
    const q = (typeof queryToRun === 'string' ? queryToRun : question).trim();
    if (!q || loading) return;

    setLoading(true);
    setError(null);
    setCopied(false);

    try {
      const res = await nl2sqlQuery(q, 2, 8);
      const data = res?.data;

      if (!data || data.status === 'failed') {
        setError(data?.error || 'Query could not be completed. Please refine your question.');
        setResponse(data);
      } else {
        setResponse(data);
      }
    } catch (err) {
      console.error('NL-to-SQL query error:', err);
      let errorMsg = 'Failed to execute natural-language query. Please ensure backend is running.';
      if (err?.response?.data?.detail) {
        errorMsg = typeof err.response.data.detail === 'string' ? err.response.data.detail : JSON.stringify(err.response.data.detail);
      } else if (err?.code === 'ECONNABORTED') {
        errorMsg = 'Request timed out while waiting for AI generation. Please try again.';
      }
      setError(errorMsg);
      setResponse(null);
    } finally {
      setLoading(false);
    }
  }

  function handleCopySQL(sqlText) {
    if (!sqlText) return;
    navigator.clipboard.writeText(sqlText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const results = response?.results || [];
  const columns = response?.columns || (results.length > 0 ? Object.keys(results[0]) : []);
  const attempts = response?.attempts || [];
  const retrievalItems = response?.retrieval?.items || [];
  const retryCount = response?.retry_count || 0;

  return (
    <div className={`flex flex-col h-full ${compact ? 'p-2' : 'p-4 max-w-5xl mx-auto'}`}>
      {/* Header */}
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-1">
          <div className="w-8 h-8 rounded-lg bg-[var(--accent-dim)] flex items-center justify-center">
            <Sparkles size={16} className="text-[var(--accent-bright)]" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)]">
              Semantic NL-to-SQL Engine
            </h2>
            <p className="text-xs text-[var(--text-muted)]">
              Grounded with FAISS embeddings &bull; SQLGlot AST validation &bull; Self-healing SQLite execution
            </p>
          </div>
        </div>

        {/* Suggested Queries */}
        <div className="flex items-center gap-1.5 flex-wrap mt-3">
          <span className="text-[11px] font-medium text-[var(--text-muted)] mr-1">Examples:</span>
          {SAMPLE_QUERIES.map((sample) => (
            <button
              key={sample}
              onClick={() => {
                setQuestion(sample);
                handleSubmit(sample);
              }}
              disabled={loading}
              className="text-[11px] px-2.5 py-1 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] transition-all disabled:opacity-50"
            >
              {sample}
            </button>
          ))}
        </div>
      </div>

      {/* Input Box */}
      <div className="mb-4">
        <div className="flex items-center gap-2 rounded-xl border border-[var(--border-strong)] bg-[var(--bg-surface)] p-2 focus-within:border-[var(--accent)] shadow-sm transition-all">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSubmit()}
            placeholder="Ask any question about your database in plain English..."
            disabled={loading}
            className="flex-1 bg-transparent text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none px-2 py-1"
          />
          <button
            onClick={() => handleSubmit()}
            disabled={!question.trim() || loading}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-xs font-medium hover:opacity-90 disabled:opacity-40 transition-all shadow-md"
          >
            {loading ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                <span>Processing...</span>
              </>
            ) : (
              <>
                <Send size={13} />
                <span>Query</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Loading State Animation */}
      {loading && (
        <Motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-6 my-4 text-center space-y-3"
        >
          <div className="w-10 h-10 rounded-full bg-[var(--accent-dim)] flex items-center justify-center mx-auto animate-pulse">
            <Loader2 size={20} className="animate-spin text-[var(--accent-bright)]" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-medium text-[var(--text-primary)]">Executing Semantic Pipeline...</p>
            <p className="text-xs text-[var(--text-muted)]">
              Retrieving schema via FAISS &rarr; Qwen3.5:4b generation &rarr; SQLGlot validation &rarr; SQLite execution
            </p>
          </div>
        </Motion.div>
      )}

      {/* Error Message */}
      {error && !loading && (
        <Motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-[var(--danger)]/30 bg-[var(--danger)]/10 p-4 mb-4 text-sm text-[var(--danger)] flex items-start gap-3"
        >
          <AlertTriangle size={18} className="flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-semibold text-xs uppercase tracking-wider mb-0.5">Query Error</p>
            <p className="text-xs leading-relaxed">{error}</p>
          </div>
        </Motion.div>
      )}

      {/* Success Response */}
      {response && !loading && (
        <div className="space-y-4 flex-1 overflow-y-auto pr-1">
          {/* 1. Natural Language Explanation Card */}
          {response.explanation && (
            <Motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 shadow-sm"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-[var(--accent-bright)]">
                  Answer & Explanation
                </span>
                {retryCount > 0 && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--warning)]/15 text-[var(--warning)] border border-[var(--warning)]/30 font-medium">
                    Self-Corrected ({retryCount} {retryCount === 1 ? 'retry' : 'retries'})
                  </span>
                )}
              </div>
              <p className="text-sm text-[var(--text-primary)] leading-relaxed">
                {response.explanation}
              </p>
            </Motion.div>
          )}

          {/* 2. SQL Candidate and Validation Badge */}
          {response.sql && (
            <Motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.05 }}
              className="rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] overflow-hidden"
            >
              <div className="flex items-center justify-between px-4 py-2 bg-[var(--bg-elevated)] border-b border-[var(--border-default)]">
                <div className="flex items-center gap-2">
                  <Terminal size={14} className="text-[var(--accent-bright)]" />
                  <span className="text-xs font-mono font-semibold text-[var(--text-primary)]">
                    Generated SQLite Query
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {response.validation?.valid ? (
                    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--success)] bg-[var(--success)]/10 px-2 py-0.5 rounded border border-[var(--success)]/20">
                      <CheckCircle2 size={11} /> SQLGlot Validated
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--danger)] bg-[var(--danger)]/10 px-2 py-0.5 rounded border border-[var(--danger)]/20">
                      <AlertTriangle size={11} /> Invalid SQL
                    </span>
                  )}
                  <button
                    onClick={() => handleCopySQL(response.sql)}
                    className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface)] transition-all"
                    title="Copy SQL"
                  >
                    {copied ? <Check size={13} className="text-[var(--success)]" /> : <Copy size={13} />}
                  </button>
                </div>
              </div>
              <pre className="p-3.5 text-xs font-mono text-[var(--text-primary)] bg-[var(--bg-void)] overflow-x-auto whitespace-pre-wrap leading-relaxed">
                {response.sql}
              </pre>
            </Motion.div>
          )}

          {/* 3. Results Table */}
          {results && results.length > 0 && (
            <Motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] overflow-hidden"
            >
              <div className="flex items-center justify-between px-4 py-2.5 bg-[var(--bg-elevated)] border-b border-[var(--border-default)]">
                <div className="flex items-center gap-2">
                  <Database size={14} className="text-[var(--text-secondary)]" />
                  <span className="text-xs font-medium text-[var(--text-primary)]">
                    Execution Results
                  </span>
                  <span className="text-xs font-mono text-[var(--text-muted)]">
                    ({response.row_count || results.length} rows)
                  </span>
                </div>
                <div className="text-[11px] font-mono text-[var(--text-muted)]">
                  Latency: {response.execution?.execution_time_ms ?? response.total_latency_ms ?? 0} ms
                </div>
              </div>

              <div className="overflow-x-auto max-h-72">
                <table className="text-xs w-full text-left">
                  <thead className="bg-[var(--bg-surface)] border-b border-[var(--border-default)] sticky top-0 z-10">
                    <tr>
                      <th className="px-3.5 py-2 text-[var(--text-muted)] font-mono text-[11px] w-12 border-r border-[var(--border-default)]">
                        #
                      </th>
                      {columns.map((col) => (
                        <th
                          key={col}
                          className="px-3.5 py-2 font-medium text-[var(--text-primary)] whitespace-nowrap"
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-default)]">
                    {results.map((row, rIdx) => (
                      <tr key={rIdx} className="hover:bg-[var(--bg-elevated)]/60 transition-colors">
                        <td className="px-3.5 py-2 text-[var(--text-muted)] font-mono text-[11px] border-r border-[var(--border-default)]">
                          {rIdx + 1}
                        </td>
                        {columns.map((col, cIdx) => {
                          const val = row[col];
                          const isNull = val === null || val === undefined;
                          return (
                            <td
                              key={cIdx}
                              className="px-3.5 py-2 text-[var(--text-secondary)] font-mono whitespace-nowrap max-w-[240px] truncate"
                            >
                              {isNull ? (
                                <span className="text-[var(--text-muted)] italic">null</span>
                              ) : (
                                String(val)
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {response.truncated && (
                <div className="px-4 py-2 bg-[var(--bg-elevated)] border-t border-[var(--border-default)] text-[11px] text-[var(--text-muted)] flex items-center gap-1.5">
                  <Info size={12} />
                  <span>Results truncated to the maximum display limit (200 rows).</span>
                </div>
              )}
            </Motion.div>
          )}

          {/* Empty Rows Result */}
          {results && results.length === 0 && response.status === 'success' && (
            <div className="rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-6 text-center text-xs text-[var(--text-muted)]">
              Query executed successfully, but returned 0 rows.
            </div>
          )}

          {/* 4. Self-Correction Trace (if retried) */}
          {attempts.length > 1 && (
            <div className="rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] overflow-hidden">
              <button
                onClick={() => setShowCorrection(!showCorrection)}
                className="w-full flex items-center justify-between px-4 py-2.5 bg-[var(--bg-elevated)] hover:bg-[var(--bg-elevated)]/80 text-left transition-all"
              >
                <div className="flex items-center gap-2">
                  <Zap size={14} className="text-[var(--warning)]" />
                  <span className="text-xs font-semibold text-[var(--text-primary)]">
                    Self-Correction History ({attempts.length} attempts)
                  </span>
                </div>
                {showCorrection ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>

              <AnimatePresence>
                {showCorrection && (
                  <Motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="p-4 space-y-3 divide-y divide-[var(--border-default)]"
                  >
                    {attempts.map((att, idx) => (
                      <div key={idx} className={idx > 0 ? 'pt-3 space-y-1.5' : 'space-y-1.5'}>
                        <div className="flex items-center justify-between">
                          <span className="text-[11px] font-mono font-semibold text-[var(--text-primary)]">
                            Attempt {att.attempt}
                          </span>
                          {att.validation?.valid ? (
                            <span className="text-[10px] text-[var(--success)] bg-[var(--success)]/10 px-2 py-0.5 rounded">
                              Valid
                            </span>
                          ) : (
                            <span className="text-[10px] text-[var(--danger)] bg-[var(--danger)]/10 px-2 py-0.5 rounded">
                              Invalid
                            </span>
                          )}
                        </div>
                        <pre className="p-2 text-[11px] font-mono bg-[var(--bg-void)] rounded border border-[var(--border-default)] overflow-x-auto text-[var(--text-secondary)]">
                          {att.sql}
                        </pre>
                        {att.validation?.errors?.length > 0 && (
                          <div className="text-[11px] text-[var(--danger)] bg-[var(--danger)]/10 p-2 rounded border border-[var(--danger)]/20">
                            {att.validation.errors.map((e, ei) => (
                              <p key={ei}>&bull; {e.message}</p>
                            ))}
                          </div>
                        )}
                        {att.execution?.error && (
                          <div className="text-[11px] text-[var(--danger)] bg-[var(--danger)]/10 p-2 rounded border border-[var(--danger)]/20">
                            &bull; Runtime Error: {att.execution.error}
                          </div>
                        )}
                      </div>
                    ))}
                  </Motion.div>
                )}
              </AnimatePresence>
            </div>
          )}

          {/* 5. Semantic Retrieval Context Accordion */}
          {retrievalItems.length > 0 && (
            <div className="rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] overflow-hidden">
              <button
                onClick={() => setShowRetrieval(!showRetrieval)}
                className="w-full flex items-center justify-between px-4 py-2.5 bg-[var(--bg-elevated)] hover:bg-[var(--bg-elevated)]/80 text-left transition-all"
              >
                <div className="flex items-center gap-2">
                  <ShieldCheck size={14} className="text-[var(--accent)]" />
                  <span className="text-xs font-semibold text-[var(--text-primary)]">
                    Retrieved Schema Context (FAISS cosine similarity)
                  </span>
                </div>
                {showRetrieval ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>

              <AnimatePresence>
                {showRetrieval && (
                  <Motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="p-3 space-y-2"
                  >
                    <div className="grid grid-cols-2 gap-2">
                      {retrievalItems.map((item, idx) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between p-2 rounded-lg border border-[var(--border-default)] bg-[var(--bg-void)] text-xs"
                        >
                          <div className="flex items-center gap-1.5 truncate">
                            <span className="text-[10px] uppercase font-mono px-1 py-0.5 rounded bg-[var(--accent-dim)] text-[var(--accent-bright)]">
                              {item.type}
                            </span>
                            <span className="font-mono text-[var(--text-primary)] truncate">
                              {item.table}{item.column ? `.${item.column}` : ''}
                            </span>
                          </div>
                          <span className="font-mono text-[11px] text-[var(--accent-bright)] flex-shrink-0 ml-2">
                            {typeof item.score === 'number' ? item.score.toFixed(4) : item.score}
                          </span>
                        </div>
                      ))}
                    </div>
                  </Motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
