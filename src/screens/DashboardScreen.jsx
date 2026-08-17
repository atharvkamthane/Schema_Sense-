import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Database, ShieldCheck, BarChart2, GitBranch,
  AlertTriangle, CheckCircle2, TrendingUp, FileText,
  Zap, ArrowRight, Eye, Download, Sparkles
} from 'lucide-react';
import PDFExportModal from '../components/PDFExportModal';
import { useAppStore } from '../store/useAppStore';
import { useVisualizationStore } from '../store/useVisualizationStore';
import { getRelationships, getSchemaWithCache, getQuality } from '../api/api';
import DBViz3D from '../components/DBViz3D';
import { normalizeQualityItems, toDisplayHealthScore } from '../utils/reportData';

function inferGroupFromName(name) {
  const n = String(name || '').toLowerCase();
  if (n.includes('customer')) return 'customer';
  if (n.includes('order')) return 'order';
  if (n.includes('product')) return 'product';
  if (n.includes('seller')) return 'seller';
  if (n.includes('review')) return 'review';
  if (n.includes('geo') || n.includes('location')) return 'geo';
  if (n.includes('payment') || n.includes('finance')) return 'finance';
  if (n.includes('inventory') || n.includes('stock')) return 'inventory';
  if (n.includes('shipping') || n.includes('delivery')) return 'shipping';
  return 'default';
}

function normalizeGraphData(relationshipsPayload, qualityPayload) {
  const nodesRaw = Array.isArray(relationshipsPayload?.nodes) ? relationshipsPayload.nodes : [];
  const edgesRaw = Array.isArray(relationshipsPayload?.edges) ? relationshipsPayload.edges : [];

  const resolveId = (v) => {
    if (typeof v === 'string') return v;
    if (v && typeof v === 'object') return v.id || v.name || v.table || v.table_name || '';
    return '';
  };

  const qualityItems = Array.isArray(qualityPayload) ? qualityPayload : [];
  const qualityMap = new Map();
  qualityItems.forEach((q) => {
    const key = String(q.table || q.table_name || '').toLowerCase();
    qualityMap.set(key, Number(q.health_score ?? q.score ?? 0));
  });

  const tables = nodesRaw.map((n) => {
    const id = String(n.id || n.name || n.table_name || '');
    const key = id.toLowerCase();
    return {
      id,
      name: n.display_name || n.label || n.name || id,
      rows: n.row_count || 0,
      columns: n.columns || [],
      qualityScore: Number(qualityMap.get(key) ?? 0),
      group: inferGroupFromName(id),
    };
  });

  const relationships = edgesRaw
    .map((e) => {
      const source = resolveId(e.source) || String(e.source_table || e.source_table_name || '');
      const target = resolveId(e.target) || String(e.target_table || e.target_table_name || '');
      if (!source || !target) return null;
      return {
        id: e.id,
        source,
        target,
        sourceCol: e.source_col,
        targetCol: e.target_col,
        type: e.type || 'explicit',
        cardinality: e.cardinality || 'one_to_many',
        label: e.label || '',
      };
    })
    .filter(Boolean);

  return { tables, relationships };
}

const fadeUp = {
  hidden: { opacity: 0, y: 14 },
  visible: (i) => ({
    opacity: 1, y: 0,
    transition: { duration: 0.4, delay: i * 0.07, ease: [0.16, 1, 0.3, 1] }
  })
};

export default function DashboardScreen() {
  const navigate = useNavigate();
  const { schema, setSchema, qualityData, setQualityData, userContext } = useAppStore();
  const { setGraphData, setVisualMode } = useVisualizationStore();
  const [loading, setLoading] = useState(true);
  const [pdfOpen, setPdfOpen] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const [schemaResult, qualityResult, relationshipsResult] = await Promise.allSettled([
          getSchemaWithCache(),
          getQuality(),
          getRelationships(),
        ]);

        if (schemaResult.status !== 'fulfilled') {
          throw new Error('Schema request failed');
        }

        const schemaRes = schemaResult.value;
        const qualityPayload = qualityResult.status === 'fulfilled' ? qualityResult.value?.data : [];
        const normalizedQuality = normalizeQualityItems(qualityPayload);
        setSchema(schemaRes.data);
        setQualityData(normalizedQuality);

        if (relationshipsResult.status === 'fulfilled') {
          const normalizedGraph = normalizeGraphData(relationshipsResult.value?.data, normalizedQuality);
          if (normalizedGraph.tables.length > 0) {
            setGraphData(normalizedGraph);
            setVisualMode('default');
            return;
          }
        }

          setGraphData({
            tables: schemaRes?.data?.tables || [],
            relationships: schemaRes?.data?.relationships || [],
          });
        setVisualMode('default');
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [setSchema, setQualityData]);

  const tableCount = schema?.tables?.length ?? 0;
  const normalizedQualityData = normalizeQualityItems(qualityData);
  const metricsQuality = normalizedQualityData.length > 0
    ? normalizedQualityData
    : (schema?.tables?.map((table) => ({
      table: table.name,
      health_score: toDisplayHealthScore(table.qualityScore),
    })) || []);
  const healthScores = metricsQuality
    .map((table) => toDisplayHealthScore(table.health_score ?? table.qualityScore))
    .filter((score) => score !== null);
  const avgHealth = healthScores.length
    ? Math.round(healthScores.reduce((sum, score) => sum + score, 0) / healthScores.length)
    : 0;
  const criticalTables = metricsQuality.filter((table) => {
    const score = toDisplayHealthScore(table.health_score ?? table.qualityScore);
    return score !== null && score < 70;
  });
  const totalColumns = schema?.tables?.reduce((s, t) => s + (t.columns?.length ?? 0), 0) ?? 0;

  const healthColor = avgHealth >= 85
    ? 'text-[var(--success)]'
    : avgHealth >= 70
    ? 'text-[var(--warning)]'
    : 'text-[var(--danger)]';

  return (
    <div className="min-h-screen w-full bg-[var(--bg-base)] p-6">
      <div className="max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="flex items-center justify-between mb-8"
        >
          <div>
            <p className="text-xs text-[var(--text-muted)] uppercase tracking-widest mb-1">
              SchemaSense AI
            </p>
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">
              Dataset Overview
            </h1>
            <p className="text-sm text-[var(--text-secondary)] mt-0.5">
              {tableCount} tables loaded · Analysis complete
            </p>
          </div>
          <button
            onClick={() => setPdfOpen(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)]
                       text-white text-sm font-medium hover:opacity-90 transition-opacity"
          >
            <Download size={15} />
            Export AI Report
          </button>
        </motion.div>

        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            {
              icon: Database, label: 'Tables', value: tableCount, sub: `${totalColumns} total columns`,
              color: 'text-[var(--accent-bright)]', bg: 'bg-[var(--accent-dim)]',
            },
            {
              icon: ShieldCheck, label: 'Avg Health Score', value: `${avgHealth}/100`,
              sub: avgHealth >= 85 ? 'Good shape' : avgHealth >= 70 ? 'Needs attention' : 'Critical issues',
              color: healthColor, bg: 'bg-[var(--accent-dim)]',
            },
            {
              icon: AlertTriangle, label: 'Critical Tables', value: criticalTables.length,
              sub: criticalTables.length ? criticalTables.slice(0,2).map(t=>t.table).join(', ') : 'None detected',
              color: criticalTables.length ? 'text-[var(--danger)]' : 'text-[var(--success)]',
              bg: criticalTables.length ? 'bg-[var(--danger)]/10' : 'bg-[var(--success)]/10',
            },
            {
              icon: Zap, label: 'AI Ready', value: 'qwen3.5:4b', sub: 'Running locally',
              color: 'text-[var(--success)]', bg: 'bg-[var(--success)]/10',
            },
          ].map((kpi, i) => (
            <motion.div key={kpi.label} custom={i} initial="hidden" animate="visible" variants={fadeUp} className="rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-4">
              <div className={`w-8 h-8 rounded-lg ${kpi.bg} flex items-center justify-center mb-3`}>
                <kpi.icon size={16} className={kpi.color} />
              </div>
              <p className="text-xs text-[var(--text-muted)] uppercase tracking-wide mb-1">{kpi.label}</p>
              <p className={`text-2xl font-bold font-mono ${kpi.color}`}>{loading ? '—' : kpi.value}</p>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">{kpi.sub}</p>
            </motion.div>
          ))}
        </div>

        <div className="grid grid-cols-3 gap-4 mb-4">
          <motion.div custom={4} initial="hidden" animate="visible" variants={fadeUp} className="col-span-2 rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] overflow-hidden relative" style={{ height: 320 }}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-default)] z-10 relative bg-[var(--bg-surface)]">
              <div className="flex items-center gap-2">
                <GitBranch size={15} className="text-[var(--accent)]" />
                <span className="text-sm font-medium text-[var(--text-primary)]">Schema Graph</span>
                <span className="text-xs text-[var(--text-muted)] ml-1">{tableCount} nodes</span>
              </div>
              <button onClick={() => navigate('/visualization')} className="flex items-center gap-1 text-xs text-[var(--accent-bright)] hover:text-[var(--accent)] transition-colors">
                Explore full graph <ArrowRight size={12} />
              </button>
            </div>
            <div className="h-[271px] w-full relative bg-[var(--bg-void)]">
               {!loading && <DBViz3D miniMode={true} />}
            </div>
          </motion.div>

          <motion.div custom={5} initial="hidden" animate="visible" variants={fadeUp} className="rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] overflow-hidden" style={{ height: 320 }}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-default)]">
              <div className="flex items-center gap-2">
                <ShieldCheck size={15} className="text-[var(--accent)]" />
                <span className="text-sm font-medium text-[var(--text-primary)]">Quality</span>
              </div>
              <button onClick={() => navigate('/quality')} className="text-xs text-[var(--accent-bright)] hover:text-[var(--accent)] flex items-center gap-1 transition-colors">
                View all <ArrowRight size={12} />
              </button>
            </div>
            <div className="p-3 overflow-y-auto" style={{ maxHeight: 272 }}>
              {loading ? (
                <div className="space-y-2">
                  {[...Array(5)].map((_, i) => <div key={i} className="h-10 rounded-lg bg-[var(--bg-elevated)] animate-pulse" />)}
                </div>
              ) : (
                metricsQuality.slice(0, 8).map((table, i) => {
                  const score = toDisplayHealthScore(table.health_score ?? table.qualityScore);
                  const safeScore = score ?? 0;
                  const color = score >= 85 ? 'var(--success)' : score >= 70 ? 'var(--warning)' : 'var(--danger)';
                  return (
                    <motion.div key={table.table} custom={i} initial="hidden" animate="visible" variants={fadeUp} onClick={() => navigate('/quality')} className="flex items-center gap-3 p-2 rounded-lg mb-1 hover:bg-[var(--bg-elevated)] cursor-pointer transition-colors duration-150">
                      <div className="w-8 h-8 rounded-lg bg-[var(--bg-elevated)] flex items-center justify-center flex-shrink-0">
                        <span className="text-xs font-bold font-mono" style={{ color: `var(--${color.replace('var(--','').replace(')','')})` }}>{score === null ? 'N/A' : score}</span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-[var(--text-primary)] truncate">{table.table}</p>
                        <div className="mt-1 h-1 rounded-full bg-[var(--bg-elevated)]">
                          <div className="h-1 rounded-full transition-all duration-700" style={{ width: `${safeScore}%`, backgroundColor: `var(--${color.replace('var(--','').replace(')','')})` }} />
                        </div>
                      </div>
                    </motion.div>
                  );
                })
              )}
            </div>
          </motion.div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[
            { icon: Sparkles, title: 'Semantic NL-to-SQL', desc: 'Ask questions in English with self-correcting SQL', route: '/query', color: 'text-[var(--accent-bright)]', bg: 'bg-[var(--accent-dim)]' },
            { icon: Database, title: 'Data Dictionary', desc: 'Schema, types, PK/FK, AI descriptions', route: '/dictionary', color: 'text-[var(--accent-bright)]', bg: 'bg-[var(--accent-dim)]' },
            { icon: BarChart2, title: 'Statistical Analysis', desc: 'Distributions, outliers, correlations', route: '/analysis', color: 'text-[var(--warning)]', bg: 'bg-[var(--warning)]/10' },
            { icon: ShieldCheck, title: 'Quality Report', desc: 'Completeness, freshness, consistency', route: '/quality', color: 'text-[var(--success)]', bg: 'bg-[var(--success)]/10' },
            { icon: GitBranch, title: 'ER Visualization', desc: '3D graph, 2D ER, analytics view', route: '/visualization', color: 'text-[var(--accent)]', bg: 'bg-[var(--accent-dim)]' },
          ].map((card, i) => (
            <motion.button key={card.title} custom={i + 6} initial="hidden" animate="visible" variants={fadeUp} onClick={() => navigate(card.route)} whileHover={{ y: -3 }} transition={{ duration: 0.15 }} className="rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 text-left hover:border-[var(--border-strong)] transition-colors duration-200 group">
              <div className={`w-9 h-9 rounded-lg ${card.bg} flex items-center justify-center mb-3`}>
                <card.icon size={18} className={card.color} />
              </div>
              <p className="text-sm font-semibold text-[var(--text-primary)] mb-1">{card.title}</p>
              <p className="text-xs text-[var(--text-muted)] leading-relaxed">{card.desc}</p>
              <div className="flex items-center gap-1 mt-3 text-xs text-[var(--accent-bright)] opacity-0 group-hover:opacity-100 transition-opacity">
                Open <ArrowRight size={11} />
              </div>
            </motion.button>
          ))}
        </div>
      </div>

      <PDFExportModal open={pdfOpen} onClose={() => setPdfOpen(false)} schemaData={schema} qualityData={metricsQuality} userContext={userContext} />
    </div>
  );
}