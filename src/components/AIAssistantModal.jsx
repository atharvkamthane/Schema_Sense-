import { useState, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  MessageSquare, X, Send, Loader2,
  Database, ShieldCheck, BarChart2, GitBranch, 
  Home, Sparkles
} from 'lucide-react';
import { postQueryPayload } from '../api/api';
import SemanticNL2SQLPanel from './SemanticNL2SQLPanel';

const SCREEN_CONTEXT = {
  '/dashboard':     'The user is viewing the Dashboard — dataset overview, health scores, quality summary.',
  '/dictionary':    'The user is viewing the Data Dictionary — table schemas, column types, PK/FK relationships, AI descriptions.',
  '/quality':       'The user is viewing the Quality Report — health scores, completeness, freshness, consistency, orphan records.',
  '/analysis':      'The user is viewing Statistical Analysis — distributions, outliers, correlations, modelling readiness.',
  '/visualization': 'The user is viewing the ER Visualization — 3D force graph, 2D ER diagram, relationship structure.',
  '/query':         'The user is querying the database using Semantic NL-to-SQL.',
};

const SCREEN_ICON = {
  '/dashboard':     Home,
  '/dictionary':    Database,
  '/quality':       ShieldCheck,
  '/analysis':      BarChart2,
  '/visualization': GitBranch,
  '/query':         Sparkles,
};

const SCREEN_SUGGESTIONS = {
  '/dashboard': [
    'Which table has the worst data quality?',
    'Summarize the entire dataset for me',
    'What are the top 3 issues I should fix first?',
  ],
  '/dictionary': [
    'Explain the relationships between these tables',
    'Which columns are most likely foreign keys?',
    'What does the PK column in this table represent?',
  ],
  '/quality': [
    'Why does this table have a low health score?',
    'Which columns have the most nulls?',
    'What SQL would fix the orphan record issue?',
  ],
  '/analysis': [
    'What does high skewness in this column mean?',
    'Which columns are correlated and why does it matter?',
    'Which columns should I transform before ML?',
  ],
  '/visualization': [
    'Describe the relationship structure of this schema',
    'Which tables are most central in this graph?',
    'Are there any circular dependencies?',
  ],
  '/query': [
    'How many surveys are there?',
    'How many survey responses are there?',
    'Which survey has the most responses?',
  ],
};

export default function AIAssistantModal({ schemaContext }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState('nl2sql'); // 'nl2sql' | 'context_chat'
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const location = useLocation();
  const messagesEndRef = useRef(null);
  
  const screenContext = SCREEN_CONTEXT[location.pathname] ?? 'General SchemaSense AI dashboard.';
  const screenSuggestions = SCREEN_SUGGESTIONS[location.pathname] ?? [];
  const ScreenIcon = SCREEN_ICON[location.pathname] ?? MessageSquare;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    setMessages([]);
  }, [location.pathname]);

  async function sendMessage(text) {
    if (!text.trim() || loading) return;
    const userMsg = { role: 'user', content: text };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const systemPrompt = `You are the SchemaSense AI assistant.
CURRENT SCREEN CONTEXT: ${screenContext}
DATASET SCHEMA SUMMARY: ${schemaContext ?? 'Schema not yet loaded'}
`;
      const response = await postQueryPayload({
        query: text,
        system_context: systemPrompt,
        screen: location.pathname,
      });
      const data = response.data;
      const rows = Array.isArray(data.data) ? data.data : (Array.isArray(data.results) ? data.results : []);
      
      const aiMsg = {
        role: 'assistant',
        content: data.natural_answer ?? data.explanation ?? data.answer ?? data.sql ?? 'No response',
        sql: data.sql,
        results: rows,
      };
      setMessages(prev => [...prev, aiMsg]);
    } catch (e) {
      let errorText = 'Request failed. Please try again.';
      if (e?.code === 'ECONNABORTED') {
        errorText = 'The AI is taking longer than expected. Please retry in a few seconds.';
      } else if (!e?.response) {
        errorText = 'Cannot reach backend. Ensure API is running on http://127.0.0.1:8000.';
      } else {
        const detail = e?.response?.data?.detail;
        if (typeof detail === 'string' && detail.trim()) {
          errorText = detail;
        } else if (typeof e?.response?.data?.explanation === 'string' && e.response.data.explanation.trim()) {
          errorText = e.response.data.explanation;
        }
      }

      setMessages(prev => [...prev, {
        role: 'assistant',
        content: errorText,
        error: true,
      }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <motion.button
        onClick={() => setOpen(true)}
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        className="fixed bottom-6 right-6 z-40 flex items-center gap-2 px-4 py-3
                   rounded-full bg-[var(--accent)] text-white shadow-lg
                   hover:opacity-90 transition-opacity"
        style={{ boxShadow: '0 0 24px rgba(99,102,241,0.4)' }}
      >
        <Sparkles size={16} />
        <span className="text-sm font-medium">Ask AI</span>
      </motion.button>

      <AnimatePresence>
        {open && (
          <>
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              onClick={() => setOpen(false)}
              className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
            />
            <motion.div
              initial={{ opacity: 0, y: 40, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 40, scale: 0.97 }}
              transition={{ type: 'spring', stiffness: 300, damping: 28 }}
              className="fixed bottom-6 right-6 z-50 flex flex-col rounded-2xl
                         border border-[var(--border-strong)] bg-[var(--bg-surface)]
                         overflow-hidden shadow-2xl"
              style={{ width: 540, height: 640, maxWidth: 'calc(100vw - 48px)', maxHeight: 'calc(100vh - 48px)' }}
            >
              {/* Header */}
              <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-default)] flex-shrink-0 bg-[var(--bg-surface)]">
                <div className="flex items-center gap-2">
                  <div className="flex items-center gap-1 bg-[var(--bg-elevated)] p-1 rounded-lg border border-[var(--border-default)]">
                    <button
                      onClick={() => setTab('nl2sql')}
                      className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-all ${
                        tab === 'nl2sql'
                          ? 'bg-[var(--accent)] text-white shadow-sm'
                          : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                      }`}
                    >
                      <Sparkles size={12} />
                      <span>NL-to-SQL</span>
                    </button>
                    <button
                      onClick={() => setTab('context_chat')}
                      className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-all ${
                        tab === 'context_chat'
                          ? 'bg-[var(--accent)] text-white shadow-sm'
                          : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                      }`}
                    >
                      <MessageSquare size={12} />
                      <span>Screen Assistant</span>
                    </button>
                  </div>
                </div>
                <button
                  onClick={() => setOpen(false)}
                  className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--bg-elevated)] transition-colors"
                >
                  <X size={16} />
                </button>
              </div>

              {/* Tab Content */}
              {tab === 'nl2sql' ? (
                <div className="flex-1 overflow-y-auto bg-[var(--bg-base)]">
                  <SemanticNL2SQLPanel compact={true} />
                </div>
              ) : (
                <div className="flex-1 flex flex-col overflow-hidden">
                  <div className="flex-1 overflow-y-auto p-4 space-y-3">
                    {messages.length === 0 && (
                      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="h-full flex flex-col items-center justify-center text-center p-4">
                        <div className="w-12 h-12 rounded-2xl bg-[var(--accent-dim)] flex items-center justify-center mb-3">
                          <Sparkles size={22} className="text-[var(--accent-bright)]" />
                        </div>
                        <p className="text-sm font-medium text-[var(--text-primary)] mb-1">Screen Context Assistant</p>
                        <p className="text-xs text-[var(--text-muted)] mb-5 max-w-[280px]">
                          I understand your current screen ({location.pathname.replace('/', '') || 'dashboard'}). Ask about schemas, quality, or insights.
                        </p>
                        <div className="space-y-2 w-full">
                          {screenSuggestions.map((s) => (
                            <button
                              key={s}
                              onClick={() => sendMessage(s)}
                              className="w-full text-left text-xs px-3 py-2.5 rounded-lg border border-[var(--border-default)] text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] transition-all"
                            >
                              {s}
                            </button>
                          ))}
                        </div>
                      </motion.div>
                    )}

                    {messages.map((msg, i) => (
                      <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        {msg.role === 'user' ? (
                          <div className="max-w-[85%] px-3 py-2 rounded-2xl rounded-tr-sm bg-[var(--accent)] text-white text-sm">
                            {msg.content}
                          </div>
                        ) : (
                          <div className="max-w-[95%] space-y-2">
                            {msg.sql && (
                              <div className="rounded-xl overflow-hidden border border-[var(--border-default)]">
                                <div className="flex items-center justify-between px-3 py-1.5 bg-[var(--bg-elevated)] border-b border-[var(--border-default)]">
                                  <span className="text-xs font-mono text-[var(--accent-bright)]">SQL</span>
                                </div>
                                <pre className="p-3 text-xs font-mono text-[var(--text-primary)] bg-[var(--bg-void)] overflow-x-auto whitespace-pre-wrap">{msg.sql}</pre>
                              </div>
                            )}
                            <div className={`px-3 py-2.5 rounded-2xl rounded-tl-sm text-sm leading-relaxed ${msg.error ? 'bg-[var(--danger)]/10 text-[var(--danger)] border border-[var(--danger)]/20' : 'bg-[var(--bg-elevated)] text-[var(--text-secondary)]'}`}>
                              {msg.content}
                            </div>
                            {msg.results?.length > 0 && (
                              <div className="rounded-xl overflow-hidden border border-[var(--border-default)]">
                                <div className="overflow-x-auto max-h-32">
                                  <table className="text-xs w-full">
                                    <thead className="bg-[var(--bg-elevated)]">
                                      <tr>{Object.keys(msg.results[0]).map(k => <th key={k} className="px-3 py-1.5 text-left font-medium text-[var(--text-muted)] whitespace-nowrap">{k}</th>)}</tr>
                                    </thead>
                                    <tbody>
                                      {msg.results.slice(0, 5).map((row, ri) => (
                                        <tr key={ri} className="border-t border-[var(--border-default)]">
                                          {Object.values(row).map((v, vi) => <td key={vi} className="px-3 py-1.5 text-[var(--text-secondary)] font-mono whitespace-nowrap max-w-[120px] truncate">{String(v)}</td>)}
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </motion.div>
                    ))}
                    {loading && (
                      <div className="flex justify-start">
                        <div className="flex items-center gap-2 px-3 py-2.5 rounded-2xl rounded-tl-sm bg-[var(--bg-elevated)] text-[var(--text-muted)]">
                          <Loader2 size={13} className="animate-spin" />
                          <span className="text-xs">Analyzing...</span>
                        </div>
                      </div>
                    )}
                    <div ref={messagesEndRef} />
                  </div>

                  <div className="flex-shrink-0 px-3 py-3 border-t border-[var(--border-default)] bg-[var(--bg-surface)]">
                    <div className="flex items-center gap-2 rounded-xl border border-[var(--border-default)] bg-[var(--bg-elevated)] px-3 py-2 focus-within:border-[var(--accent)] transition-colors">
                      <input
                        value={input} onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage(input)}
                        placeholder="Ask about your data..."
                        className="flex-1 bg-transparent text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none"
                      />
                      <button onClick={() => sendMessage(input)} disabled={!input.trim() || loading} className="p-1.5 rounded-lg bg-[var(--accent)] text-white disabled:opacity-40 transition-opacity">
                        <Send size={13} />
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}