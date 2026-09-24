import { useEffect, useState, useRef } from "react"
import { bustSchemaCache, getSchema, uploadFile, clearDatabase } from "../api/api"
import { AnimatePresence, motion } from "framer-motion"
import { useAppStore } from "../store/useAppStore"
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ShoppingCart,
  TrendingUp,
  UploadCloud,
  Users,
} from "lucide-react"

const SAMPLE_DATASETS = [
  {
    id: "olist",
    name: "Olist E-Commerce",
    subtitle: "Marketplace orders, customers, and reviews",
    meta: "99K rows · 11 cols",
    icon: ShoppingCart,
    iconBg: "rgba(249,115,22,0.1)",
    iconColor: "#fb923c",
  },
  {
    id: "chinook",
    name: "Chinook Music",
    subtitle: "Artists, albums, invoices, and tracks",
    meta: "3K rows · 14 cols",
    icon: Users,
    iconBg: "rgba(59,130,246,0.1)",
    iconColor: "#60a5fa",
  },
  {
    id: "bike",
    name: "Bike Store",
    subtitle: "Retail operations and sales performance",
    meta: "4.1K rows · 9 cols",
    icon: TrendingUp,
    iconBg: "rgba(16,185,129,0.1)",
    iconColor: "#34d399",
  },
]

function AnimatedHeroLine({ text, accent = false }) {
  return (
    <motion.span
      className={`inline-block ${accent ? "text-[var(--text-accent)]" : "text-[var(--text-primary)]"}`}
      initial="hidden"
      animate="visible"
      variants={{
        hidden: {},
        visible: {
          transition: {
            staggerChildren: 0.06,
          },
        },
      }}
    >
      {text.split(" ").map((word, idx) => (
        <motion.span
          key={`${word}-${idx}`}
          className="mr-2 inline-block"
          variants={{
            hidden: { opacity: 0, y: 10 },
            visible: { opacity: 1, y: 0, transition: { duration: 0.35 } },
          }}
        >
          {word}
        </motion.span>
      ))}
    </motion.span>
  )
}

function withTimeout(promise, timeoutMs, timeoutMessage = "Request timed out") {
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error(timeoutMessage)), timeoutMs)
    }),
  ])
}

export default function UploadScreen({ onContinue }) {
  const { setUserContext, userContext } = useAppStore();
  const [fileName, setFileName] = useState("")
  const [fileCount, setFileCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [progress, setProgress] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [verifiedTables, setVerifiedTables] = useState(0)
  const [verifiedColumns, setVerifiedColumns] = useState(0)
  const fileInputRef = useRef(null)
  const autoContinueTimerRef = useRef(null)
  const hardSafetyTimerRef = useRef(null)
  const continueScheduledRef = useRef(false)

  const clearContinueTimers = () => {
    if (autoContinueTimerRef.current) {
      clearTimeout(autoContinueTimerRef.current)
      autoContinueTimerRef.current = null
    }
    if (hardSafetyTimerRef.current) {
      clearTimeout(hardSafetyTimerRef.current)
      hardSafetyTimerRef.current = null
    }
  }

  const scheduleContinue = (delayMs = 0) => {
    if (continueScheduledRef.current) return
    continueScheduledRef.current = true

    if (hardSafetyTimerRef.current) {
      clearTimeout(hardSafetyTimerRef.current)
      hardSafetyTimerRef.current = null
    }

    autoContinueTimerRef.current = setTimeout(() => {
      setFileCount(0)
      setProgress(0)
      onContinue()
    }, delayMs)
  }

  useEffect(() => {
    return () => {
      clearContinueTimers()
    }
  }, [])

  function handleSampleDataset(name) {
    setError("")
    setNotice("")
    setFileName(`${name} (Demo)`)
    setTimeout(() => onContinue(), 500)
  }

  async function handleFileUpload(files) {
    if (!files || files.length === 0) return

    try {
      clearContinueTimers()
      continueScheduledRef.current = false

      setLoading(true)
      setError("")
      setNotice("")
      setFileCount(files.length)
      setProgress(0)
      setVerifiedTables(0)
      setVerifiedColumns(0)

      // Option A: Clear previous database explicitly before parallel uploads begin to avoid race conditions.
      try {
        await clearDatabase()
      } catch (clearErr) {
        console.warn("Could not clear previous database prior to upload:", clearErr)
      }

      const fileList = Array.from(files)
      let uploadedCount = 0

      await Promise.all(
        fileList.map(async (file) => {
          await uploadFile(file)
          uploadedCount += 1
          setFileName(`${uploadedCount}/${fileList.length}: ${file.name}`)
          setProgress((uploadedCount / fileList.length) * 100)
        })
      )

      // Invalidate schema cache so dictionary/visualization pull fresh tables.
      bustSchemaCache()

      // Hard safety: never block users at 100% if verification hangs.
      hardSafetyTimerRef.current = setTimeout(() => {
        console.warn("Upload safety continue triggered after verification delay")
        scheduleContinue(0)
      }, 10000)

      // Verify backend actually has the expected number of tables.
      let tableCount = 0
      try {
        const schemaRes = await withTimeout(
          getSchema(),
          6000,
          "Schema verification timed out"
        )
        const schemaTables = Array.isArray(schemaRes?.data?.tables) ? schemaRes.data.tables : []
        tableCount = schemaTables.length
        const totalColumns = schemaTables.reduce((sum, table) => {
          const cols = Array.isArray(table?.columns) ? table.columns.length : 0
          return sum + cols
        }, 0)
        setVerifiedTables(tableCount)
        setVerifiedColumns(totalColumns)
      } catch (schemaErr) {
        console.warn("Schema verification after upload failed", schemaErr)
      }

      let showNotice = false
      if (files.length > 1 && tableCount <= 1) {
        showNotice = true
        setNotice("Backend currently shows only 1 table after multi-file upload. Ask Member 1 to append files during ingest, or upload a single ZIP containing all CSVs.")
      } else if (tableCount > files.length + 3) {
        showNotice = true
        setNotice(`Note: Backend database now contains ${tableCount} tables. It appears previous datasets were not cleared. (Ask Member 1 to wipe the DB on new uploads if this is unintended).`)
      }

      // After all files uploaded, wait and continue
      scheduleContinue(showNotice ? 4500 : 1200)

    } catch (err) {
      console.error(err)
      if (err?.code === "ERR_NETWORK" || (err?.message || "").includes("ERR_NGROK")) {
        setError("Backend is unreachable. Start your local FastAPI server on http://127.0.0.1:8000 and try again.")
      } else if ((err?.message || "").toLowerCase().includes("timeout")) {
        setError("Upload is taking longer than expected. Please wait and retry with a smaller file batch if needed.")
      } else {
        setError(`Upload failed: ${err?.message || "Unknown error"}. Try again.`)
      }
    } finally {
      setLoading(false)
      // Reset file input so same file can be uploaded again
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
    }
  }

  const uploadComplete = progress === 100 && !loading

  return (
    <div className="min-h-screen px-6 pb-10 pt-6 md:px-10">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-44 left-1/3 h-[340px] w-[340px] rounded-full bg-[var(--accent-dim)] blur-[110px]" />
        <div className="absolute bottom-[-140px] right-[-80px] h-[320px] w-[320px] rounded-full bg-[rgba(59,130,246,0.09)] blur-[130px]" />
      </div>

      <div className="relative mx-auto flex min-h-[92vh] w-full max-w-[860px] flex-col">
        <div className="mb-8 flex items-center gap-2 text-xs text-[var(--text-muted)]">
          <span>SchemaSense AI</span>
          <span>/</span>
          <span className="text-[var(--text-primary)]">Upload</span>
        </div>

        <section className="pb-12 pt-16 text-center">
          <motion.div
            className="mx-auto inline-flex rounded-full border border-[rgba(129,140,248,0.3)] bg-[var(--accent-dim)] px-3 py-1"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.3 }}
          >
            <span className="font-mono text-xs tracking-[0.07em] text-[var(--accent-bright)]">
              Autonomous AI Data Dictionary &amp; Schema Intelligence Agent
            </span>
          </motion.div>

          <h1 className="mt-4 flex flex-col text-4xl font-semibold leading-[1.15] md:text-[42px]">
            <AnimatedHeroLine text="Connect any database." />
            <AnimatedHeroLine text="Get intelligence in seconds." accent />
          </h1>

          <motion.p
            className="mx-auto mt-3 max-w-md text-base leading-relaxed text-[var(--text-secondary)]"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: 0.2 }}
          >
            Upload flat files or packaged datasets and instantly generate a query-ready schema layer with reasoning, quality checks, and relationship discovery.
          </motion.p>
        </section>

        <section className="mt-1">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".csv,.json,.zip,.sqlite,.db"
            onChange={(e) => handleFileUpload(e.target.files)}
            style={{ display: "none" }}
            disabled={loading}
          />

          <motion.div
            role="button"
            tabIndex={0}
            onClick={() => fileInputRef.current?.click()}
            onDragEnter={(e) => {
              e.preventDefault()
              setIsDragging(true)
            }}
            onDragOver={(e) => {
              e.preventDefault()
              setIsDragging(true)
            }}
            onDragLeave={(e) => {
              e.preventDefault()
              setIsDragging(false)
            }}
            onDrop={(e) => {
              e.preventDefault()
              setIsDragging(false)
              handleFileUpload(e.dataTransfer.files)
            }}
            className={`relative flex h-[200px] w-full cursor-pointer flex-col items-center justify-center rounded-[var(--radius-xl)] border-2 border-dashed transition-all duration-200 ${
              isDragging
                ? "border-[var(--accent)] bg-[var(--accent-dim)]"
                : "border-[var(--border-strong)] bg-[var(--bg-surface)]"
            }`}
            animate={{ scale: isDragging ? 1.01 : 1 }}
            transition={{ duration: 0.2 }}
          >
            <AnimatePresence mode="wait">
              {uploadComplete ? (
                <motion.div
                  key="upload-complete"
                  className="flex flex-col items-center gap-2"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                >
                  <svg className="h-11 w-11" viewBox="0 0 52 52" fill="none">
                    <circle cx="26" cy="26" r="24" stroke="rgba(16,185,129,0.24)" strokeWidth="2" />
                    <path
                      d="M15 27L22 34L38 18"
                      stroke="var(--success)"
                      strokeWidth="3"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      style={{ strokeDasharray: 100, strokeDashoffset: 0, animation: "draw 0.5s ease" }}
                    />
                  </svg>
                  <p className="text-sm text-[var(--text-primary)]">{fileName || "Dataset uploaded"}</p>
                  <span className="badge badge-success">
                    {verifiedTables || 1} tables · {verifiedColumns || 0} columns
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      clearContinueTimers()
                      continueScheduledRef.current = true
                      onContinue()
                    }}
                    className="mt-1 rounded-[var(--radius-md)] border border-[var(--border-accent)] bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white transition hover:bg-[var(--accent-bright)]"
                  >
                    Continue to Dictionary →
                  </button>
                </motion.div>
              ) : (
                <motion.div
                  key="upload-idle"
                  className="flex flex-col items-center"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                >
                  <UploadCloud
                    className={`h-8 w-8 ${isDragging ? "text-[var(--accent-bright)]" : "text-[var(--text-muted)]"}`}
                  />
                  <p className="mt-3 text-sm text-[var(--text-secondary)]">
                    {isDragging ? "Release to upload" : "Drop files here"}
                  </p>
                  <p className="mt-1 text-xs text-[var(--text-muted)]">or</p>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      fileInputRef.current?.click()
                    }}
                    className="mt-2 rounded-[var(--radius-md)] border border-[var(--border-default)] bg-transparent px-3 py-1.5 text-xs text-[var(--text-secondary)] transition hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
                  >
                    Browse files
                  </button>
                  <div className="mt-3 flex flex-wrap justify-center gap-2">
                    {[
                      "CSV",
                      "JSON",
                      "SQLite",
                      "ZIP",
                    ].map((format) => (
                      <span key={format} className="badge badge-muted">
                        {format}
                      </span>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>

          <AnimatePresence>
            {loading && fileCount > 0 ? (
              <motion.div
                className="mt-4"
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
              >
                <div className="mb-1 flex items-center justify-between text-xs text-[var(--text-muted)]">
                  <span>Uploading {fileName || "dataset.csv"}</span>
                  <span>{Math.round(progress)}%</span>
                </div>
                <div className="h-[2px] w-full overflow-hidden bg-[var(--border-default)]">
                  <motion.div
                    className="h-full bg-[var(--accent)]"
                    animate={{ width: `${progress}%` }}
                    transition={{ duration: 0.2, ease: "linear" }}
                  />
                </div>
              </motion.div>
            ) : null}
          </AnimatePresence>
        </section>

        <section className="mt-12">
          <div className="flex items-center gap-4">
            <hr className="flex-1 border-0 border-t border-[var(--border-default)]" />
            <span className="text-center text-xs uppercase tracking-[0.2em] text-[var(--text-muted)]">
              Start with a sample dataset
            </span>
            <hr className="flex-1 border-0 border-t border-[var(--border-default)]" />
          </div>

          
          {/* USER CONTEXT FIELD */}
          <div className="w-full relative mt-6 mb-2 text-left z-10">
            <label className="text-sm font-medium text-[var(--text-secondary)] mb-2 block">
              What is this data for? (Optional context for AI)
            </label>
            <textarea
              placeholder="E.g., I am analyzing e-commerce transactions for Q3 to spot churn patterns..."
              className="w-full bg-[var(--bg-surface)] border border-[var(--border-light)] rounded-xl p-3 text-[var(--text-primary)] text-sm focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)] min-h-[80px] resize-none pb-8"
              value={userContext || ""}
              onChange={(e) => setUserContext(e.target.value)}
            />
            <button 
              className="absolute bottom-3 right-3 text-xs bg-[var(--bg-surface-hover)] hover:bg-[var(--accent-primary)] hover:text-white px-2 py-1 rounded-md transition-colors text-[var(--text-tertiary)]"
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setUserContext("I want to understand the relationship between order volumes, shipping delays, and overall customer satisfaction scores over the last 6 months."); }}
            >
              Auto-fill example
            </button>
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-3">
            {SAMPLE_DATASETS.map((sample, idx) => {
              const Icon = sample.icon
              return (
                <motion.button
                  key={sample.id}
                  onClick={() => handleSampleDataset(sample.name)}
                  className="group card relative p-5 text-left"
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.32, delay: idx * 0.1 }}
                  whileHover={{ y: -3 }}
                >
                  <span
                    className="grid h-9 w-9 place-items-center rounded-[var(--radius-md)]"
                    style={{ background: sample.iconBg }}
                  >
                    <Icon className="h-4 w-4" style={{ color: sample.iconColor }} />
                  </span>
                  <h3 className="mt-3 text-sm font-semibold text-[var(--text-primary)]">{sample.name}</h3>
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">{sample.subtitle}</p>
                  <p className="mt-3 font-mono text-xs text-[var(--text-muted)]">{sample.meta}</p>
                  <span className="absolute bottom-5 right-5 text-xs text-[var(--accent-bright)] opacity-0 transition-opacity group-hover:opacity-100">
                    Load →
                  </span>
                </motion.button>
              )
            })}
          </div>

          <AnimatePresence>
            {uploadComplete ? (
              <motion.div
                className="mt-5 inline-flex items-center gap-2 rounded-full border border-[rgba(16,185,129,0.3)] bg-[var(--success-dim)] px-3 py-1 text-xs text-[var(--success)]"
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
                Schema verified. {Math.max(verifiedTables, 1)} tables loaded.
              </motion.div>
            ) : null}
          </AnimatePresence>

          <AnimatePresence>
            {notice ? (
              <motion.div
                className="mt-3 flex items-center gap-2 rounded-[var(--radius-md)] border border-[rgba(245,158,11,0.35)] bg-[var(--warning-dim)] px-3 py-2 text-xs text-[var(--warning)]"
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
              >
                <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                {notice}
              </motion.div>
            ) : null}
          </AnimatePresence>

          <AnimatePresence>
            {error ? (
              <motion.div
                className="mt-3 flex items-center gap-2 rounded-[var(--radius-md)] border border-[rgba(239,68,68,0.35)] bg-[var(--danger-dim)] px-3 py-2 text-xs text-[var(--danger)]"
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
              >
                <AlertCircle className="h-4 w-4 flex-shrink-0" />
                {error}
              </motion.div>
            ) : null}
          </AnimatePresence>
        </section>
      </div>
    </div>
  )
}