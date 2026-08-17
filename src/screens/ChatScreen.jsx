import { useRef, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { postQueryPayload } from "../api/api"
import { Send, AlertCircle, CheckCircle, Loader, Bot, MessageSquare, Sparkles } from "lucide-react"
import { useVisualizationStore } from "../store/useVisualizationStore"
import SemanticNL2SQLPanel from "../components/SemanticNL2SQLPanel"

function normalizeUserQuestion(question) {
  const q = String(question || "").trim()
  const lower = q.toLowerCase()

  const sortIntent = /(sort|order\s*by|ascending|descending|asc\b|desc\b)/i.test(lower)
  const shortSortPattern = /^sort\s+(ascendingly|descendingly|asc|desc)?\s*(for|by)?\s+[a-zA-Z0-9_]+\s*$/i

  if (sortIntent && shortSortPattern.test(q)) {
    const colMatch = q.match(/([a-zA-Z_][a-zA-Z0-9_]*)\s*$/)
    const col = colMatch ? colMatch[1] : "id"
    const direction = /(desc|descending)/i.test(lower) ? "descending" : "ascending"
    return `Show top 20 rows sorted by ${col} in ${direction} order. Use a read-only SELECT query.`
  }

  return q
}

function shouldRetryWithClarifiedPrompt(body) {
  const explanation = String(body?.explanation || body?.message || "").toLowerCase()
  const executionError = String(body?.execution_error || "").toLowerCase()
  const sql = String(body?.sql || body?.query || "").trim().toLowerCase()

  const hasFallbackSignal =
    body?.used_fallback === true ||
    explanation.includes("empty sql generated") ||
    explanation.includes("self-correction") ||
    explanation.includes("returning fallback data") ||
    executionError.length > 0

  const sqlLooksInvalid = !sql || (!sql.startsWith("select") && !sql.startsWith("with"))
  return hasFallbackSignal && sqlLooksInvalid
}

function buildRetryPrompt(question) {
  return [
    "Rewrite the request into a single valid read-only SQL task.",
    "Use only SELECT/WITH SQL semantics.",
    "If sorting is requested, include ORDER BY with ASC/DESC.",
    `User request: ${question}`,
  ].join("\n")
}

function hasExecutionIssue(msg) {
  if (msg?.execution_ok === false && msg?.used_fallback !== true) return true

  const executionError = String(msg?.execution_error || "").trim()
  if (executionError.length > 0) return true
  if (msg?.execution_ok === false) return true
  
  return false
}

function isFallbackWithData(msg) {
  if (msg?.used_fallback === true) return true

  const hasData = Array.isArray(msg?.results) && msg.results.length > 0
  const hasError = String(msg?.execution_error || "").trim().length > 0
  return hasData && hasError
}

export default function ChatScreen() {
  const [activeTab, setActiveTab] = useState("nl2sql") // "nl2sql" | "legacy_chat"
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState("")
  const [isThinking, setIsThinking] = useState(false)
  const messageIdRef = useRef(0)
  const highlightQueriedTables = useVisualizationStore((s) => s.highlightQueriedTables)

  async function handleSend(questionOverride) {
    if (isThinking) return

    const questionValue =
      typeof questionOverride === "string" ? questionOverride : input

    if (!questionValue.trim()) return

    const normalizedQuestion = normalizeUserQuestion(questionValue)
    const userMsg = { id: ++messageIdRef.current, role: "user", text: questionValue }

    setMessages((prev) => [...prev, userMsg])
    setInput("")
    setIsThinking(true)

    try {
      let res = await postQueryPayload({ query: normalizedQuestion })
      let body = res?.data || {}

      if (shouldRetryWithClarifiedPrompt(body)) {
        const retryPrompt = buildRetryPrompt(normalizedQuestion)
        res = await postQueryPayload({ query: retryPrompt })
        body = res?.data || {}
      }

      const queriedTables = Array.isArray(body.queried_tables) ? body.queried_tables : []
      const results = Array.isArray(body.data) ? body.data : (Array.isArray(body.results) ? body.results : [])

      const aiMsg = {
        id: ++messageIdRef.current,
        role: "ai",
        kind: "result",
        sql: body.sql ?? body.query ?? "No SQL returned",
        natural_answer: body.natural_answer ?? body.answer ?? "",
        explanation: body.explanation ?? body.message ?? "No explanation returned",
        results,
        execution_ok: body.execution_ok,
        execution_error: body.execution_error,
        used_fallback: body.used_fallback
      }

      setMessages((prev) => [...prev, aiMsg])

      if (queriedTables.length > 0) {
        highlightQueriedTables(queriedTables)
      }
    } catch (err) {
      console.error(err)
      setMessages((prev) => [
        ...prev,
        {
          role: "ai",
          id: ++messageIdRef.current,
          kind: "network_error",
          error: "Something went wrong. Please try again.",
          retryQuestion: questionValue
        }
      ])
    } finally {
      setIsThinking(false)
    }
  }

  return (
    <div className="h-screen overflow-hidden bg-[var(--bg-base)] flex flex-col">
      <header className="flex h-[76px] items-center justify-between border-b border-[var(--border-default)] px-6 flex-shrink-0">
        <div>
          <div className="flex items-center gap-1 text-xs text-[var(--text-muted)]">
            <span>SchemaSense AI</span>
            <span>/</span>
            <span className="text-[var(--text-primary)]">Query & Chat</span>
          </div>
          <h1 className="mt-1 text-base font-semibold text-[var(--text-primary)]">Natural Language SQL Engine</h1>
        </div>

        {/* Tab Controls */}
        <div className="flex items-center gap-2 bg-[var(--bg-surface)] p-1 rounded-xl border border-[var(--border-default)]">
          <button
            onClick={() => setActiveTab("nl2sql")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === "nl2sql"
                ? "bg-[var(--accent)] text-white shadow-sm"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            <Sparkles size={13} />
            <span>Semantic NL-to-SQL</span>
          </button>
          <button
            onClick={() => setActiveTab("legacy_chat")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === "legacy_chat"
                ? "bg-[var(--accent)] text-white shadow-sm"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            <MessageSquare size={13} />
            <span>Conversational Chat</span>
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      {activeTab === "nl2sql" ? (
        <div className="flex-1 overflow-y-auto p-6 bg-[var(--bg-base)]">
          <SemanticNL2SQLPanel compact={false} />
        </div>
      ) : (
        <div className="grid h-[calc(100vh-76px)] grid-rows-[1fr_auto]">
          <div className="overflow-y-auto px-4 py-5 md:px-6">
            <div className="mx-auto max-w-5xl space-y-4">
              {messages.length === 0 && (
                <div className="card grid min-h-[260px] place-items-center border border-[var(--border-default)]">
                  <div className="text-center">
                    <Bot className="mx-auto mb-3 h-7 w-7 text-[var(--text-muted)]" />
                    <p className="text-sm text-[var(--text-secondary)]">Ask anything about your dataset.</p>
                    <p className="mt-1 font-mono text-xs text-[var(--text-muted)]">Example: Show top 20 orders by total_price desc</p>
                  </div>
                </div>
              )}

              <AnimatePresence>
                {messages.map((msg, i) => (
                  <motion.div
                    key={msg.id ?? i}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    transition={{ duration: 0.3 }}
                  >
                    {msg.role === "user" && (
                      <div className="mb-4 flex justify-end">
                        <motion.div
                          initial={{ scale: 0.97 }}
                          animate={{ scale: 1 }}
                          className="inline-block max-w-xs rounded-2xl border border-[var(--border-accent)] bg-[var(--accent-dim)] px-4 py-3 text-sm text-[var(--text-primary)] shadow-[var(--shadow-sm)] lg:max-w-md"
                        >
                          {msg.text}
                        </motion.div>
                      </div>
                    )}

                    {msg.role === "ai" && (
                      <div className="mb-4 flex justify-start">
                        <div className="w-full max-w-3xl">
                          {msg.kind === "network_error" ? (
                            <div className="flex gap-3 rounded-[var(--radius-lg)] border border-[rgba(239,68,68,0.35)] bg-[var(--danger-dim)] p-4">
                              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-[var(--danger)]" />
                              <div className="flex-1">
                                <p className="mb-3 text-sm text-[var(--danger)]">{msg.error}</p>
                                <button
                                  onClick={() => handleSend(msg.retryQuestion)}
                                  className="rounded-[var(--radius-md)] border border-[var(--border-accent)] bg-[var(--accent-dim)] px-3 py-1.5 text-xs text-[var(--accent-bright)] transition hover:bg-[rgba(99,102,241,0.25)]"
                                >
                                  Retry
                                </button>
                              </div>
                            </div>
                          ) : (
                            <motion.div
                              initial={{ opacity: 0 }}
                              animate={{ opacity: 1 }}
                              className="card space-y-3 rounded-[var(--radius-lg)] border border-[var(--border-default)] p-4"
                            >
                              {(() => {
                                const hasIssue = hasExecutionIssue(msg)
                                const fallbackData = isFallbackWithData(msg)
                                const isSuccess = msg.execution_ok === true && !hasIssue

                                return (
                                  <>
                                    {fallbackData && (
                                      <div className="flex gap-2 rounded-[var(--radius-sm)] border border-[rgba(245,158,11,0.35)] bg-[var(--warning-dim)] p-3">
                                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--warning)]" />
                                        <p className="text-xs text-[var(--warning)]">
                                          Backend returned fallback rows due to SQL guardrails. Results may not match your question exactly.
                                        </p>
                                      </div>
                                    )}

                                    {hasIssue && !fallbackData && (
                                      <div className="flex gap-2 rounded-[var(--radius-sm)] border border-[rgba(239,68,68,0.35)] bg-[var(--danger-dim)] p-3">
                                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--danger)]" />
                                        <p className="text-xs text-[var(--danger)]">
                                          {msg.execution_error || "Query fallback/error detected in execution details."}
                                        </p>
                                      </div>
                                    )}

                                    {isSuccess && (
                                      <div className="flex gap-2 rounded-[var(--radius-sm)] border border-[rgba(16,185,129,0.35)] bg-[var(--success-dim)] p-3">
                                        <CheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--success)]" />
                                        <p className="text-xs text-[var(--success)]">Query executed successfully</p>
                                      </div>
                                    )}
                                  </>
                                )
                              })()}

                              <div className="rounded-[var(--radius-md)] border border-[var(--border-accent)] bg-[var(--accent-dim)] p-3">
                                <p className="mb-1 text-xs font-semibold uppercase tracking-[0.1em] text-[var(--accent-bright)]">Answer</p>
                                <p className="text-sm leading-relaxed text-[var(--text-primary)]">{String(msg.natural_answer || msg.explanation || "No answer returned")}</p>
                              </div>

                              <div className="rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-elevated)] p-3">
                                <p className="mb-1 text-xs font-semibold uppercase tracking-[0.1em] text-[var(--text-muted)]">Generated SQL</p>
                                <pre className="overflow-x-auto text-xs font-mono text-[var(--accent-bright)]">{msg.sql}</pre>
                              </div>

                              {Array.isArray(msg.results) && msg.results.length > 0 && (
                                <div className="overflow-x-auto rounded-[var(--radius-md)] border border-[var(--border-default)]">
                                  <table className="w-full text-left text-xs">
                                    <thead className="border-b border-[var(--border-default)] bg-[var(--bg-elevated)] text-[var(--text-muted)]">
                                      <tr>
                                        {Object.keys(msg.results[0] || {}).map((col) => (
                                          <th key={col} className="px-3 py-2 font-medium">{col}</th>
                                        ))}
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-[var(--border-default)]">
                                      {msg.results.slice(0, 10).map((row, rIdx) => (
                                        <tr key={rIdx} className="hover:bg-[var(--bg-elevated)]">
                                          {Object.values(row).map((val, cIdx) => (
                                            <td key={cIdx} className="px-3 py-2 font-mono text-[var(--text-secondary)]">
                                              {val === null ? <span className="text-[var(--text-muted)] italic">null</span> : String(val)}
                                            </td>
                                          ))}
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              )}
                            </motion.div>
                          )}
                        </div>
                      </div>
                    )}
                  </motion.div>
                ))}
              </AnimatePresence>

              {isThinking && (
                <div className="flex items-center gap-2 p-3 text-sm text-[var(--text-muted)]">
                  <Loader className="h-4 w-4 animate-spin text-[var(--accent)]" />
                  <span>AI is analyzing schema and querying...</span>
                </div>
              )}
            </div>
          </div>

          <div className="border-t border-[var(--border-default)] p-4 bg-[var(--bg-surface)]">
            <div className="mx-auto flex max-w-5xl items-center gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
                placeholder="Ask a question about your database..."
                disabled={isThinking}
                className="flex-1 rounded-xl border border-[var(--border-default)] bg-[var(--bg-elevated)] px-4 py-2.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
              />
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || isThinking}
                className="flex items-center gap-1.5 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
              >
                <Send className="h-4 w-4" />
                <span>Send</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}