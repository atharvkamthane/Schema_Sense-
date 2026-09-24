import { useEffect } from "react"
import { Layers3, BarChart3, RefreshCw, AlertTriangle, Network } from "lucide-react"
import DBViz3D from "../components/DBViz3D"
import ERDiagram2D from "../components/ERDiagram2D"
import AnalyticsDashboard from "../components/AnalyticsDashboard"
import NodeDetailOverlay from "../components/NodeDetailOverlay"
import { useVisualizationStore } from "../store/useVisualizationStore"
import { getQuality, getRelationships } from "../api/api"

function inferGroupFromName(name) {
  const n = String(name || "").toLowerCase()
  if (n.includes("customer")) return "customer"
  if (n.includes("order")) return "order"
  if (n.includes("product")) return "product"
  if (n.includes("seller")) return "seller"
  if (n.includes("review")) return "review"
  if (n.includes("geo") || n.includes("location")) return "geo"
  if (n.includes("payment") || n.includes("finance")) return "finance"
  if (n.includes("inventory") || n.includes("stock")) return "inventory"
  if (n.includes("shipping") || n.includes("delivery")) return "shipping"
  return "default"
}

function normalizeGraphData(relationshipsPayload, qualityPayload) {
  const nodesRaw = Array.isArray(relationshipsPayload?.nodes) ? relationshipsPayload.nodes : []
  const edgesRaw = Array.isArray(relationshipsPayload?.edges) ? relationshipsPayload.edges : []

  const resolveId = (v) => {
    if (typeof v === "string") return v
    if (v && typeof v === "object") return v.id || v.name || v.table || v.table_name || ""
    return ""
  }

  const qualityItems = Array.isArray(qualityPayload?.items) ? qualityPayload.items : []
  const qualityMap = new Map()
  qualityItems.forEach((q) => {
    const k = String(q.table || q.table_name || "").toLowerCase()
    qualityMap.set(k, Number(q.health_score ?? 0))
  })

  const tables = nodesRaw.map((n) => {
    const id = String(n.id || n.name || n.table_name || "")
    const key = id.toLowerCase()
    return {
      id,
      name: n.display_name || n.label || n.name || id,
      rows: n.row_count || 0,
      columns: n.columns || [],
      qualityScore: Number(qualityMap.get(key) ?? 0),
      group: inferGroupFromName(id),
    }
  })

  // Normalize relationships/edges
  const relationships = edgesRaw
    .map((e) => {
      const source = resolveId(e.source)
      const target = resolveId(e.target)
      const fallbackSource = String(e.source_table || e.source_table_name || "")
      const fallbackTarget = String(e.target_table || e.target_table_name || "")
      const finalSource = source || fallbackSource
      const finalTarget = target || fallbackTarget
      if (!finalSource || !finalTarget) return null

      return {
        id: e.id,
        source: finalSource,
        target: finalTarget,
        sourceCol: e.source_col,
        targetCol: e.target_col,
        type: e.type || "explicit",
        cardinality: e.cardinality || "one_to_many",
        label: e.label || "",
        confidence: e.confidence,
        inferenceMethod: e.inference_method,
      }
    })
    .filter(Boolean)

  return { tables, relationships }
}

export default function Visualization3D() {
  const {
    setGraphData,
    tables,
    relationships,
    loading,
    error,
    setLoading,
    setError,
    viewMode,
    setViewMode,
    visualMode,
    setVisualMode,
    queriedTables,
    resetVisualization,
  } = useVisualizationStore()

  const loadVisualizationData = async () => {
    setLoading(true)
    setError("")

    try {
      // Relationships are required to render links. Quality is optional enhancement.
      const [relationshipsResult, qualityResult] = await Promise.allSettled([
        getRelationships(),
        getQuality(),
      ])

      if (relationshipsResult.status !== "fulfilled") {
        throw new Error("/relationships request failed")
      }

      const relationshipsData = relationshipsResult.value?.data
      const qualityData = qualityResult.status === "fulfilled" ? qualityResult.value?.data : { items: [] }

      const { tables, relationships } = normalizeGraphData(relationshipsData, qualityData)

      if (tables.length > 0) {
        setGraphData({ tables, relationships })
        return
      }

      throw new Error("Graph payload missing nodes")
    } catch (err) {
      console.error("Visualization load error:", err)
      setError("Failed to load visualization data from backend.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadVisualizationData()
    return () => resetVisualization()
  }, [])

  useEffect(() => {
    if (viewMode !== "3d" && visualMode === "quality") {
      setVisualMode("default")
    }
  }, [viewMode, visualMode, setVisualMode])

  return (
    <div className="flex flex-col h-screen w-full overflow-hidden bg-[var(--bg-base)]">
      <header className="shrink-0 flex h-14 items-center justify-between border-b border-[var(--border-default)] px-6">
        <div>
          <div className="flex items-center gap-1 text-xs text-[var(--text-muted)]">
            <span>SchemaSense AI</span>
            <span>/</span>
            <span className="text-[var(--text-primary)]">Visualization</span>
          </div>
          <h1 className="mt-1 text-base font-semibold text-[var(--text-primary)]">Schema Graph Intelligence</h1>
        </div>

        <div className="hidden items-center gap-2 md:flex">
          <span className="badge badge-muted">{tables.length} nodes</span>
          <span className="badge badge-muted">{relationships.length} edges</span>
          <span className="badge badge-accent">{viewMode.toUpperCase()} mode</span>
        </div>
      </header>

      <div className="relative flex-1 w-full h-full overflow-hidden">
      <div className="absolute left-3 top-3 z-20 flex flex-wrap items-center gap-2 rounded-[var(--radius-lg)] border border-[var(--border-default)] bg-[var(--bg-surface)]/95 p-2 shadow-[var(--shadow-md)] backdrop-blur">
        <button
          onClick={() => setViewMode("3d")}
          aria-pressed={viewMode === "3d"}
          className={`rounded-[var(--radius-md)] border px-3 py-1.5 text-sm transition-colors ${
            viewMode === "3d"
              ? "border-[var(--border-accent)] bg-[var(--accent-dim)] text-[var(--accent-bright)]"
              : "border-[var(--border-default)] bg-[var(--bg-input)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          }`}
        >
          <span className="inline-flex items-center gap-1.5"><Layers3 className="h-4 w-4" /> 3D Graph</span>
        </button>

        <button
          onClick={() => setViewMode("2d")}
          aria-pressed={viewMode === "2d"}
          className={`rounded-[var(--radius-md)] border px-3 py-1.5 text-sm transition-colors ${
            viewMode === "2d"
              ? "border-[var(--border-accent)] bg-[var(--accent-dim)] text-[var(--accent-bright)]"
              : "border-[var(--border-default)] bg-[var(--bg-input)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          }`}
        >
          <span className="inline-flex items-center gap-1.5"><Network className="h-4 w-4" /> 2D ER Diagram</span>
        </button>

        <button
          onClick={() => setViewMode("analytics")}
          aria-pressed={viewMode === "analytics"}
          className={`rounded-[var(--radius-md)] border px-3 py-1.5 text-sm transition-colors ${
            viewMode === "analytics"
              ? "border-[var(--border-accent)] bg-[var(--accent-dim)] text-[var(--accent-bright)]"
              : "border-[var(--border-default)] bg-[var(--bg-input)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          }`}
        >
          <span className="inline-flex items-center gap-1.5"><BarChart3 className="h-4 w-4" /> Analytics</span>
        </button>

        {viewMode === "3d" ? (
          <button
            onClick={() => setVisualMode(visualMode === "quality" ? "default" : "quality")}
            aria-pressed={visualMode === "quality"}
            className={`rounded-[var(--radius-md)] border px-3 py-1.5 text-sm transition-colors ${
              visualMode === "quality"
                ? "border-[rgba(245,158,11,0.35)] bg-[var(--warning-dim)] text-[var(--warning)]"
                : "border-[var(--border-default)] bg-[var(--bg-input)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            {visualMode === "quality" ? "Quality Color On" : "Quality Color Off"}
          </button>
        ) : null}

        <button
          onClick={loadVisualizationData}
          className="rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-input)] px-3 py-1.5 text-sm text-[var(--text-secondary)] transition hover:text-[var(--text-primary)]"
        >
          <span className="inline-flex items-center gap-1.5"><RefreshCw className="h-4 w-4" /> Reload</span>
        </button>

      </div>

      <div className="absolute right-3 top-3 z-20 rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)]/95 px-3 py-1.5 text-xs text-[var(--text-secondary)] backdrop-blur">
        Highlighted from chat: {queriedTables.length}
      </div>

      <div className="absolute right-3 top-14 z-20 rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-surface)]/95 px-3 py-1.5 text-xs text-[var(--text-secondary)] backdrop-blur">
        Tables: {tables.length} | Relationships: {relationships.length}
      </div>

      {!loading && !error && (tables.length <= 1 || relationships.length === 0) && (
        <div className="absolute left-3 top-16 z-20 max-w-xl rounded-[var(--radius-md)] border border-[rgba(245,158,11,0.35)] bg-[var(--warning-dim)] px-3 py-2 text-xs text-[var(--warning)]">
          Graph has limited data from backend right now ({tables.length} table, {relationships.length} relationships). If you uploaded multiple CSVs, backend ingest is likely replacing instead of appending.
        </div>
      )}

      {loading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/45 backdrop-blur-sm">
          <div className="text-center">
            <div className="mx-auto mb-3 h-10 w-10 animate-spin rounded-full border-2 border-[var(--accent)] border-t-transparent" />
            <p className="text-sm text-[var(--text-secondary)]">Loading graph data...</p>
          </div>
        </div>
      )}

      {error && !loading && (
        <div className="pointer-events-none absolute left-1/2 top-16 z-30 max-w-xl -translate-x-1/2 rounded-[var(--radius-lg)] border border-[rgba(239,68,68,0.35)] bg-[var(--danger-dim)] p-2 text-center shadow-[var(--shadow-lg)]">
          <p className="flex items-center gap-2 text-xs text-[var(--danger)]"><AlertTriangle className="h-4 w-4" />{error}</p>
        </div>
      )}

      {viewMode === "3d" ? <DBViz3D /> : viewMode === "2d" ? <ERDiagram2D /> : <AnalyticsDashboard />}
      <NodeDetailOverlay />
      </div>
    </div>
  )
}
