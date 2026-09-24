import { useMemo, useRef, useEffect, useState } from "react"
import ForceGraph3D from "react-force-graph-3d"
import * as THREE from "three"
import { useVisualizationStore } from "../store/useVisualizationStore"

function getTableColor(tableName) {
  const colors = [
      '#6366f1', '#3b82f6', '#10b981',
      '#f59e0b', '#06b6d4', '#ec4899',
      '#8b5cf6', '#14b8a6', '#f43f5e',
      '#84cc16', '#eab308'
  ]
  const idx = String(tableName || '').charCodeAt(0) % colors.length
  return colors[idx >= 0 ? idx : 0]
}

function getQualityColor(score) {
  if (score >= 85) return "#22c55e"
  if (score >= 60) return "#f59e0b"
  return "#ef4444"
}

export default function DBViz3D({ miniMode = false }) {
  const containerRef = useRef(null)
  const fgRef = useRef(null)
  const [dimensions, setDimensions] = useState(() => ({
    width: typeof window !== "undefined" ? (miniMode ? 350 : Math.max(window.innerWidth - 64, 400)) : 800,
    height: typeof window !== "undefined" ? (miniMode ? 270 : Math.max(window.innerHeight - 56, 400)) : 600,
  }))

  useEffect(() => {
    if (!containerRef.current) return

    const updateSize = () => {
      if (containerRef.current) {
        const { clientWidth, clientHeight } = containerRef.current
        if (clientWidth > 0 && clientHeight > 0) {
          setDimensions({ width: clientWidth, height: clientHeight })
        }
      }
    }

    updateSize()
    const observer = new ResizeObserver(updateSize)
    observer.observe(containerRef.current)
    window.addEventListener("resize", updateSize)

    return () => {
      observer.disconnect()
      window.removeEventListener("resize", updateSize)
    }
  }, [])
  const { tables, relationships, setSelectedNode, selectedNode, visualMode, queriedTables } = useVisualizationStore()

  const graphData = useMemo(() => {
    const total = Math.max((tables || []).length, 1)
    const baseRadius = miniMode ? 120 : 190
    const nodes = (tables || []).map((t, idx) => ({
      id: String(t.id || t.name),
      name: String(t.name),
      rows: t.rows,
      columns: t.columns,
      qualityScore: t.qualityScore,
      group: t.group,
      val: Math.max(Math.cbrt(t.rows || 1) * (miniMode ? 0.3 : 0.5), miniMode ? 1.5 : 2),
      idx,
      // Seed initial positions to avoid mini-mode overlap before the simulation settles.
      x: Math.cos((idx / total) * Math.PI * 2) * baseRadius,
      y: Math.sin((idx / total) * Math.PI * 2) * baseRadius,
      z: (idx % 2 === 0 ? 1 : -1) * baseRadius * 0.45,
    }))

    const nodeIds = new Set(nodes.map(n => n.id))

    // Fallbacks to handle slightly messy backend strings
    const resolveId = (idString) => {
       const cleaned = String(idString || '').trim()
       return cleaned
    }

    const links = (relationships || [])
      .map((r) => {
        const strictSrc = resolveId(r.source)
        const strictTgt = resolveId(r.target)
        return {
          source: strictSrc,
          target: strictTgt,
          type: r.type || 'explicit',
          label: r.sourceCol + ' -> ' + r.targetCol,
        }
      })
      .filter((l) => {
         const valid = nodeIds.has(l.source) && nodeIds.has(l.target);
         if (!valid) {
             console.warn("DBViz3D Dropping link due to missing node:", l.source, "->", l.target);
         }
         return valid;
      })

    return { nodes, links }
  }, [tables, relationships])

  useEffect(() => {
    if (!fgRef.current) return
    const timer = setTimeout(() => {
      fgRef.current?.d3Force("charge")?.strength(miniMode ? -185 : -320)
      fgRef.current?.d3Force("link")?.distance(miniMode ? 90 : 140)
      fgRef.current?.d3ReheatSimulation()
      fgRef.current?.zoomToFit(miniMode ? 560 : 650, miniMode ? 48 : 56)
    }, 60)
    
    return () => {
      clearTimeout(timer)
    }
  }, [graphData, miniMode])

  const nodeColor = (node) => {
    const nodeId = String(node.id || "").toLowerCase()
    const queried = queriedTables.includes(nodeId)

    if (visualMode === "quality") return getQualityColor(node.qualityScore || 0)
    if (visualMode === "ai-query" && queried) return "#fbbf24" // Brighter amber for query focus

    return getTableColor(node.name)
  }

  // Rich node objects restore persistent labels and make selected/query nodes
  // legible without increasing the force simulation work.
  const nodeThreeObject = (node) => {
    const isSelected = String(selectedNode?.id || "") === String(node.id)
    const isQueried = visualMode === "ai-query" && queriedTables.includes(String(node.id || "").toLowerCase())
    const color = nodeColor(node)
    const size = miniMode ? Math.max(node.val * 0.55, 2) : Math.max(node.val * 0.8, 3)
    const group = new THREE.Group()
    group.add(new THREE.Mesh(
      new THREE.SphereGeometry(size, miniMode ? 12 : 20, miniMode ? 12 : 20),
      new THREE.MeshPhongMaterial({ color, transparent: true, opacity: 0.92, shininess: 95, emissive: new THREE.Color(color), emissiveIntensity: isQueried ? 0.8 : isSelected ? 0.5 : 0.18 })
    ))

    if (!miniMode && (isSelected || isQueried)) {
      const ring = new THREE.Mesh(new THREE.RingGeometry(size * 1.25, size * 1.48, 28), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: isQueried ? 0.7 : 0.45, side: THREE.DoubleSide }))
      ring.rotation.x = Math.PI / 2
      group.add(ring)
    }

    if (!miniMode) {
      const canvas = document.createElement("canvas")
      canvas.width = 256
      canvas.height = 48
      const ctx = canvas.getContext("2d")
      if (ctx) {
        ctx.font = "600 20px Inter, sans-serif"
        ctx.fillStyle = "#f8fafc"
        ctx.textAlign = "center"
        const label = String(node.name).replace(/_/g, " ")
        ctx.fillText(label.length > 22 ? `${label.slice(0, 20)}…` : label, 128, 30)
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true }))
        sprite.scale.set(size * 4, size * 0.75, 1)
        sprite.position.y = size + 5
        group.add(sprite)
      }
    }
    return group
  }

  const particleCount = miniMode ? 0 : graphData.links.length > 36 ? 1 : 3

  return (
    <div ref={containerRef} className="absolute inset-0 w-full h-full overflow-hidden">
      <ForceGraph3D
        width={dimensions.width}
        height={dimensions.height}
        ref={fgRef}
        graphData={graphData}
        backgroundColor="rgba(0,0,0,0)"
        showNavInfo={false}
        enableNodeDrag
        enableNavigationControls
        cooldownTicks={miniMode ? 95 : 90}
        nodeColor={nodeColor}
        nodeThreeObject={nodeThreeObject}
        nodeThreeObjectExtend={false}
        nodeVal={(n) => {
          const queried = queriedTables.includes(String(n.id || "").toLowerCase())
          let val = queried && visualMode === "ai-query" ? n.val * 2.5 : n.val * 2
          if (miniMode) {
            // Keep preview readable and fully visible in the small dashboard card.
            return Math.min(Math.max(val * 0.42, 2.3), 7)
          }
          return val
        }}
        nodeResolution={miniMode ? 12 : 20}
        nodeOpacity={1}
        linkOpacity={0.65}
        nodeLabel={(node) => {
          const quality = Math.round(node.qualityScore || 0)
          return "<div style=\"padding:8px;background:#111827;border:1px solid rgba(255,255,255,0.12);border-radius:10px;color:#f8fafc;font-family:Inter,sans-serif\"><b>" + node.name + "</b><br/>Rows: " + (node.rows || 0).toLocaleString() + "<br/>Quality: " + quality + "%</div>"
        }}
        linkColor={(link) => 
            link.type === 'implicit' 
            ? 'rgba(148, 163, 184, 0.4)' 
            : 'rgba(56, 189, 248, 0.75)' // More vibrant light blue for explicit links
        }
        linkWidth={(link) => (link.type === 'implicit' ? (miniMode ? 0.5 : 1.5) : (miniMode ? 1 : 2.5))}
        linkDirectionalParticles={(link) => (link.type === 'implicit' ? 0 : particleCount)}
        linkDirectionalParticleWidth={(link) => (link.type === 'implicit' ? 1.5 : (miniMode ? 2 : 3.5))}
        linkDirectionalParticleResolution={miniMode ? 8 : 16}
        linkDirectionalParticleSpeed={(link) => (link.type === 'implicit' ? 0.005 : 0.015)}
        linkDirectionalParticleColor={(link) => 
            link.type === 'implicit' ? '#cbd5e1' : '#38bdf8'
        }
        onEngineStop={undefined}
        onNodeClick={(node) => {
          const picked = tables.find((t) => String(t.id) === String(node.id))
          if (picked) setSelectedNode(picked)

          if (miniMode) return

          const distance = miniMode ? 95 : 130
          const distRatio = 1 + distance / Math.hypot(node.x || 1, node.y || 1, node.z || 1)
          fgRef.current?.cameraPosition(
            { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
            node,
            miniMode ? 650 : 800
          )
        }}
      />
    </div>
  )
}
