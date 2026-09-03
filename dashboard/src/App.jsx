import { useState, useEffect, useCallback, useRef } from 'react'

const API = '/api'

function fmt(n) {
  if (n == null || isNaN(n)) return '₹0'
  if (Math.abs(n) >= 10000000) return '₹' + (n / 10000000).toFixed(1) + 'Cr'
  if (Math.abs(n) >= 100000) return '₹' + (n / 100000).toFixed(1) + 'L'
  if (Math.abs(n) >= 1000) return '₹' + (n / 1000).toFixed(1) + 'K'
  return '₹' + Math.round(n).toLocaleString('en-IN')
}

function fmtFull(n) {
  if (n == null) return '₹0'
  return '₹' + Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

function pct(n) { return (n * 100).toFixed(1) + '%' }

const CAUSE_COLORS = {
  insufficient_funds: '#f59e0b', bank_outage: '#ef4444', afa_stuck: '#8b5cf6',
  card_expired: '#ec4899', mandate_expired: '#06b6d4', mandate_revoked: '#64748b',
  ambiguous: '#94a3b8',
}
const ACTION_COLORS = {
  auto_retry: '#22c55e', sms_then_retry: '#3b82f6', call_then_retry: '#a855f7',
  card_update_link: '#06b6d4', mandate_resequence: '#f59e0b', escalation: '#ef4444',
  gate_blocked: '#991b1b', scheduled: '#64748b', awaiting_decision: '#64748b',
}
const CHART_COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#a855f7', '#06b6d4', '#ec4899', '#64748b', '#84cc16', '#f97316']

const CAUSE_LABELS = {
  insufficient_funds: 'Insufficient Funds', bank_outage: 'Bank Outage',
  afa_stuck: 'AFA Stuck', card_expired: 'Card Expired',
  mandate_expired: 'Mandate Expired', mandate_revoked: 'Mandate Revoked',
  ambiguous: 'Ambiguous',
}

function StatusBadge({ status }) {
  const styles = {
    resolved: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    decision_pending: 'bg-amber-100 text-amber-700 border-amber-200',
    in_progress: 'bg-blue-100 text-blue-700 border-blue-200',
    gate_blocked: 'bg-red-100 text-red-700 border-red-200',
    unprocessed: 'bg-gray-100 text-gray-500 border-gray-200',
  }
  return (
    <span className={`px-2 py-0.5 text-xs font-medium rounded-full border ${styles[status] || styles.unprocessed}`}>
      {status?.replace(/_/g, ' ')}
    </span>
  )
}

function OutcomeBadge({ outcome }) {
  if (!outcome) return null
  const styles = {
    recovered: 'bg-emerald-100 text-emerald-700',
    failed_exhausted: 'bg-red-100 text-red-700',
    gate_blocked: 'bg-red-100 text-red-700',
    escalated: 'bg-orange-100 text-orange-700',
    card_update_sent: 'bg-blue-100 text-blue-700',
    mandate_resequenced: 'bg-blue-100 text-blue-700',
    merchant_rejected: 'bg-red-100 text-red-700',
    downgrade_offered: 'bg-amber-100 text-amber-700',
  }
  return (
    <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${styles[outcome] || 'bg-gray-100 text-gray-500'}`}>
      {outcome.replace(/_/g, ' ')}
    </span>
  )
}

function TierBadge({ tier }) {
  if (!tier) return null
  const styles = {
    1: 'bg-emerald-100 text-emerald-700',
    2: 'bg-blue-100 text-blue-700',
    3: 'bg-amber-100 text-amber-700',
  }
  return (
    <span className={`px-1.5 py-0.5 text-[10px] font-semibold rounded ${styles[tier] || 'bg-gray-100 text-gray-500'}`}>
      T{tier}
    </span>
  )
}

function DonutChart({ data, size = 140 }) {
  const [hover, setHover] = useState(null)
  const total = data.reduce((s, d) => s + d.value, 0)
  if (!total) return null
  const cx = size / 2, cy = size / 2, r = size * 0.38, stroke = size * 0.14
  const circumference = 2 * Math.PI * r
  let offset = 0
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {data.map((d, i) => {
          const p = d.value / total
          const dash = p * circumference
          const gap = circumference - dash
          const o = offset
          offset += dash
          return (
            <circle key={i} cx={cx} cy={cy} r={r} fill="none"
              stroke={d.fill} strokeWidth={hover === i ? stroke + 4 : stroke}
              strokeDasharray={`${dash} ${gap}`}
              strokeDashoffset={-o}
              transform={`rotate(-90 ${cx} ${cy})`}
              style={{ cursor: 'pointer', transition: 'stroke-width 0.15s' }}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)} />
          )
        })}
        {hover !== null && (
          <>
            <text x={cx} y={cy - 6} textAnchor="middle" fill="#374151" fontSize="13" fontWeight="600">
              {(data[hover].value / total * 100).toFixed(1)}%
            </text>
            <text x={cx} y={cy + 12} textAnchor="middle" fill="#6b7280" fontSize="10">
              {data[hover].value} items
            </text>
          </>
        )}
      </svg>
    </div>
  )
}

function SvgLineChart({ data, baseline }) {
  const [hoverIdx, setHoverIdx] = useState(null)
  if (!data || data.length === 0) return <p className="text-gray-400 text-sm py-8 text-center">No timeline data</p>
  const W = 700, H = 220, pad = { t: 20, r: 60, b: 30, l: 60 }
  const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b
  const vals = data.map(d => d.net || 0)
  const maxV = Math.max(...vals, baseline || 0) * 1.1
  const minV = Math.min(0, ...vals)
  const range = maxV - minV || 1
  const x = (i) => pad.l + (i / (data.length - 1)) * cw
  const y = (v) => pad.t + ch - ((v - minV) / range) * ch
  const points = data.map((d, i) => `${x(i)},${y(d.net || 0)}`).join(' ')
  const ticks = 5
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 260 }}
      onMouseLeave={() => setHoverIdx(null)}>
      {Array.from({ length: ticks + 1 }, (_, i) => {
        const v = minV + (range / ticks) * i
        const yy = y(v)
        return <g key={i}><line x1={pad.l} x2={W - pad.r} y1={yy} y2={yy} stroke="#e5e7eb" strokeDasharray="3 3" />
          <text x={pad.l - 6} y={yy + 4} textAnchor="end" fill="#9ca3af" fontSize="10">{fmt(v)}</text></g>
      })}
      {data.filter((_, i) => i % Math.max(1, Math.floor(data.length / 6)) === 0).map((d) => {
        const idx = data.indexOf(d)
        return <text key={idx} x={x(idx)} y={H - 6} textAnchor="middle" fill="#9ca3af" fontSize="10">{d.date?.slice(5)}</text>
      })}
      {baseline && <><line x1={pad.l} x2={W - pad.r} y1={y(baseline)} y2={y(baseline)} stroke="#ef4444" strokeDasharray="8 4" strokeWidth={1.5} />
        <text x={W - pad.r + 4} y={y(baseline) + 4} fill="#ef4444" fontSize="10">Naive</text></>}
      <polyline points={points} fill="none" stroke="#22c55e" strokeWidth="2.5" strokeLinejoin="round" />
      {data.map((d, i) => (
        <circle key={i} cx={x(i)} cy={y(d.net || 0)} r={hoverIdx === i ? 5 : 3}
          fill={hoverIdx === i ? '#16a34a' : 'transparent'} stroke={hoverIdx === i ? '#16a34a' : 'transparent'}
          style={{ cursor: 'pointer' }}
          onMouseEnter={() => setHoverIdx(i)} />
      ))}
      {hoverIdx !== null && (() => {
        const d = data[hoverIdx]
        const px = x(hoverIdx), py = y(d.net || 0)
        const tipW = 120, tipH = 36
        const tx = Math.min(Math.max(px - tipW / 2, pad.l), W - pad.r - tipW)
        const ty = py - tipH - 8
        return (
          <g>
            <line x1={px} x2={px} y1={pad.t} y2={H - pad.b} stroke="#d1d5db" strokeDasharray="3 3" />
            <rect x={tx} y={ty} width={tipW} height={tipH} rx={6} fill="#1f2937" opacity={0.9} />
            <text x={tx + tipW / 2} y={ty + 14} textAnchor="middle" fill="#fff" fontSize="10">{d.date}</text>
            <text x={tx + tipW / 2} y={ty + 28} textAnchor="middle" fill="#4ade80" fontSize="11" fontWeight="600">{fmtFull(d.net || 0)}</text>
          </g>
        )
      })()}
    </svg>
  )
}

function SvgHBarChart({ data }) {
  const [hover, setHover] = useState(null)
  if (!data || data.length === 0) return <p className="text-gray-400 text-sm py-8 text-center">No bank data</p>
  const maxCount = Math.max(...data.map(d => d.count))
  return (
    <div className="space-y-2">
      {data.map((d, i) => (
        <div key={i} className="flex items-center gap-3 group cursor-pointer"
          onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
          <span className="text-xs text-gray-600 w-28 text-right truncate">{d.name}</span>
          <div className="flex-1 h-7 bg-gray-50 rounded overflow-hidden relative">
            <div className={`h-full rounded flex items-center px-2 transition-all duration-200 ${hover === i ? 'shadow-md' : ''}`} style={{
              width: `${Math.max(8, (d.count / maxCount) * 100)}%`,
              background: d.fill,
              transform: hover === i ? 'scaleY(1.15)' : 'scaleY(1)',
            }}>
              <span className="text-white text-xs font-semibold">{d.count}</span>
            </div>
            {hover === i && d.topCause && (
              <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-gray-500 bg-white/90 px-1.5 py-0.5 rounded">
                top cause: {d.topCause.replace(/_/g, ' ')}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── TOAST SYSTEM ───────────────────────────────────────────

function ToastContainer({ toasts, onDismiss }) {
  return (
    <div className="fixed top-4 right-4 z-50 space-y-2 pointer-events-none" style={{ maxWidth: '360px' }}>
      {toasts.map(t => (
        <div key={t.id}
          className={`pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium
            transition-all duration-300 animate-toast-in
            ${t.type === 'success' ? 'bg-emerald-50 border-emerald-200 text-emerald-700' :
              t.type === 'error' ? 'bg-red-50 border-red-200 text-red-700' :
              t.type === 'warning' ? 'bg-amber-50 border-amber-200 text-amber-700' :
              'bg-blue-50 border-blue-200 text-blue-700'}`}>
          <span className="text-lg flex-shrink-0">
            {t.type === 'success' ? '✓' : t.type === 'error' ? '✗' : t.type === 'warning' ? '!' : 'ℹ'}
          </span>
          <span className="flex-1">{t.message}</span>
          <button onClick={() => onDismiss(t.id)} className="opacity-50 hover:opacity-100 text-xs ml-2">✕</button>
        </div>
      ))}
    </div>
  )
}

// ─── ANIMATED COUNTER HOOK ──────────────────────────────────

function useAnimatedValue(target, duration = 800, prevStored) {
  const initFrom = prevStored != null && prevStored > 0 ? prevStored : 0
  const [value, setValue] = useState(initFrom)
  const prevTarget = useRef(initFrom)
  const [delta, setDelta] = useState(0)
  const [showDelta, setShowDelta] = useState(false)

  useEffect(() => {
    if (target == null || isNaN(target)) return
    const start = prevTarget.current
    const diff = target - start
    if (Math.abs(diff) < 1) { setValue(target); prevTarget.current = target; return }
    if (start > 0 && diff > 0) {
      setDelta(diff)
      setShowDelta(true)
      const hideTimer = setTimeout(() => setShowDelta(false), 3500)
      var cleanup = () => clearTimeout(hideTimer)
    }
    const startTime = performance.now()
    let raf
    const step = (now) => {
      const elapsed = now - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setValue(start + diff * eased)
      if (progress < 1) raf = requestAnimationFrame(step)
      else prevTarget.current = target
    }
    raf = requestAnimationFrame(step)
    return () => { cancelAnimationFrame(raf); cleanup?.() }
  }, [target, duration])

  return { value, delta, showDelta }
}

function DeltaBadge({ delta, showDelta, formatter }) {
  if (!showDelta || delta <= 0) return null
  return (
    <span className="inline-flex items-center ml-2 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700 animate-delta-badge">
      +{formatter ? formatter(delta) : delta}
    </span>
  )
}

// ─── BATCH ACTIVITY OVERLAY ─────────────────────────────────

function BatchActivityOverlay({ processing, items, overview, onDismiss, onSelectPayment }) {
  const [phase, setPhase] = useState(0)
  const [diagLines, setDiagLines] = useState([])
  const [actionLines, setActionLines] = useState([])
  const [retryFeed, setRetryFeed] = useState([])
  const [retryProgress, setRetryProgress] = useState(0)
  const [done, setDone] = useState(false)
  const feedRef = useRef(null)

  useEffect(() => {
    if (!processing) { setPhase(0); setDiagLines([]); setActionLines([]); setRetryFeed([]); setRetryProgress(0); setDone(false); return }
    setPhase(1); setDiagLines([]); setActionLines([]); setRetryFeed([]); setRetryProgress(0); setDone(false)
    return () => {}
  }, [processing])

  useEffect(() => {
    if (!processing || !items || items.length === 0) return
    const causes = {}
    const actions = {}
    items.forEach(i => {
      if (i.cause) causes[i.cause] = (causes[i.cause] || 0) + 1
      if (i.action) actions[i.action] = (actions[i.action] || 0) + 1
    })

    const causeEntries = Object.entries(causes).sort((a, b) => b[1] - a[1])
    const actionEntries = Object.entries(actions).sort((a, b) => b[1] - a[1])
    const retryItems = items.filter(i => i.outcome)
    const totalRetries = overview?.retryable_count || retryItems.length || 299

    setPhase(1)
    const diagTimers = causeEntries.map(([cause, count], i) =>
      setTimeout(() => setDiagLines(prev => [...prev, { cause, count }]), 300 + i * 250)
    )

    const actionStart = 300 + causeEntries.length * 250 + 500
    const actionTimers = actionEntries.map(([action, count], i) =>
      setTimeout(() => setActionLines(prev => [...prev, { action, count }]), actionStart + i * 200)
    )

    const phase2Start = actionStart + actionEntries.length * 200 + 800
    const phase2Timer = setTimeout(() => setPhase(2), phase2Start)

    const feedItems = retryItems.slice(0, 40)
    const feedTimers = feedItems.map((item, i) =>
      setTimeout(() => {
        setRetryFeed(prev => [...prev, item])
        setRetryProgress(Math.round(((i + 1) / feedItems.length) * totalRetries))
      }, phase2Start + 400 + i * 200)
    )

    const doneTime = phase2Start + 400 + feedItems.length * 200 + 1000
    const doneTimer = setTimeout(() => { setPhase(3); setDone(true) }, doneTime)
    const dismissTimer = setTimeout(() => { if (onDismiss) onDismiss() }, doneTime + 5000)

    return () => {
      diagTimers.forEach(clearTimeout)
      actionTimers.forEach(clearTimeout)
      feedTimers.forEach(clearTimeout)
      clearTimeout(phase2Timer)
      clearTimeout(doneTimer)
      clearTimeout(dismissTimer)
    }
  }, [items, processing, overview, onDismiss])

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight
  }, [retryFeed])

  if (!processing) return null

  const totalRetries = overview?.retryable_count || 299
  const recovered = (items || []).filter(i => i.amount_recovered > 0)
  const totalRecovered = recovered.reduce((s, i) => s + (i.amount_recovered || 0), 0)

  return (
    <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center animate-toast-in">
      <div className="bg-white rounded-2xl shadow-2xl border border-gray-200 w-full max-w-lg mx-4 overflow-hidden" style={{ maxHeight: '85vh' }}>
        <div className={`${done ? 'bg-emerald-600' : 'bg-blue-600'} text-white px-5 py-4 flex items-center justify-between transition-colors duration-500`}>
          <div className="flex items-center gap-3">
            {!done && <span className="w-3 h-3 rounded-full bg-white/40 animate-pulse" />}
            {done && <span className="text-lg">✓</span>}
            <h3 className="font-semibold">
              {phase <= 1 ? 'Diagnosing Failures...' : phase === 2 ? 'Executing Retries...' : 'Recovery Complete'}
            </h3>
          </div>
          {done && <button onClick={onDismiss} className="text-white/70 hover:text-white text-sm">Dismiss</button>}
        </div>

        <div className="p-5 space-y-3 overflow-y-auto" style={{ maxHeight: 'calc(85vh - 64px)' }}>
          {/* Indeterminate progress while backend is working */}
          {phase === 1 && diagLines.length === 0 && (
            <div className="space-y-3">
              <div className="bg-gray-100 rounded-full h-2.5 overflow-hidden">
                <div className="h-full bg-blue-500 rounded-full animate-indeterminate" />
              </div>
              <p className="text-xs text-gray-400 text-center">Processing 500 payment failures through the diagnostic pipeline...</p>
            </div>
          )}
          {/* Phase 1: Diagnosis lines */}
          {diagLines.length > 0 && (
            <div className="space-y-1">
              {diagLines.map((d, i) => (
                <div key={i} className="text-sm text-gray-700 animate-feed-in flex items-center gap-2">
                  <span className="text-emerald-500 font-bold">✓</span>
                  <span className="font-mono">{d.count}</span>
                  <span className="text-gray-500">{d.cause.replace(/_/g, ' ')} diagnosed</span>
                </div>
              ))}
            </div>
          )}

          {actionLines.length > 0 && (
            <div className="space-y-1 border-t border-gray-100 pt-2">
              {actionLines.map((a, i) => (
                <div key={i} className="text-sm text-gray-700 animate-feed-in flex items-center gap-2">
                  <span className="text-blue-500 font-bold">✓</span>
                  <span className="font-mono">{a.count}</span>
                  <span className="text-gray-500">{a.action.replace(/_/g, ' ')}</span>
                </div>
              ))}
            </div>
          )}

          {/* Phase 2: Retry progress + feed */}
          {phase >= 2 && (
            <div className="border-t border-gray-100 pt-3">
              <div className="flex justify-between text-xs text-gray-500 mb-1.5">
                <span>Executing retries... {done ? totalRetries : retryProgress}/{totalRetries}</span>
                <span className="text-emerald-600 font-semibold">
                  +{fmtFull(retryFeed.filter(r => r.amount_recovered > 0).reduce((s, r) => s + r.amount_recovered, 0))}
                </span>
              </div>
              <div className="bg-gray-100 rounded-full h-2.5 overflow-hidden mb-3">
                <div className={`h-full rounded-full transition-all duration-300 ${done ? 'bg-emerald-500' : 'bg-blue-500'}`}
                  style={{ width: `${done ? 100 : Math.min((retryProgress / totalRetries) * 100, 95)}%` }} />
              </div>
              <div ref={feedRef} className="space-y-0.5 max-h-48 overflow-y-auto">
                {retryFeed.map((item, i) => {
                  const success = item.amount_recovered > 0
                  return (
                    <div key={i} className="flex items-center gap-2 py-0.5 px-1 text-xs animate-feed-in">
                      <button onClick={() => onSelectPayment && onSelectPayment(item.payment_id)} className="font-mono text-blue-600 hover:text-blue-800 w-20 truncate text-left">{item.payment_id}</button>
                      <span className="text-gray-400">{fmtFull(item.amount)}</span>
                      <span className="text-gray-400">—</span>
                      <span className="text-gray-500">{item.action?.replace(/_/g, ' ')}</span>
                      <span className="text-gray-400">→</span>
                      {success
                        ? <span className="text-emerald-600 font-semibold">Success! ✓</span>
                        : <span className="text-red-400">Failed</span>}
                      {success && <span className="text-emerald-600 font-mono ml-auto">+{fmtFull(item.amount_recovered)}</span>}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Phase 3: Summary */}
          {done && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-center animate-card-enter">
              <p className="text-3xl font-bold text-emerald-600">{fmtFull(totalRecovered)}</p>
              <p className="text-sm text-emerald-500 mt-1">recovered from {items?.length || 0} events</p>
              <p className="text-xs text-gray-400 mt-1">{recovered.length} successful recoveries</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── CSS ANIMATIONS (injected once) ─────────────────────────

const styleTag = document.createElement('style')
styleTag.textContent = `
  @keyframes toast-in {
    from { opacity: 0; transform: translateX(100px); }
    to { opacity: 1; transform: translateX(0); }
  }
  .animate-toast-in { animation: toast-in 0.3s ease-out; }

  @keyframes feed-in {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .animate-feed-in { animation: feed-in 0.25s ease-out both; }

  @keyframes card-enter {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .animate-card-enter { animation: card-enter 0.3s ease-out both; }

  @keyframes ring-fill {
    from { stroke-dasharray: 0 264; }
  }
  .animate-ring { animation: ring-fill 1s ease-out both; }

  @keyframes count-fade {
    from { opacity: 0.3; }
    to { opacity: 1; }
  }
  .animate-count { animation: count-fade 0.6s ease-out; }

  @keyframes delta-badge {
    0% { opacity: 0; transform: translateY(8px) scale(0.8); }
    20% { opacity: 1; transform: translateY(-2px) scale(1.05); }
    40% { transform: translateY(0) scale(1); }
    80% { opacity: 1; }
    100% { opacity: 0; transform: translateY(-4px); }
  }
  .animate-delta-badge { animation: delta-badge 3s ease-out forwards; }

  @keyframes card-exit {
    0% { opacity: 1; transform: translateX(0); max-height: 300px; margin-bottom: 12px; }
    65% { opacity: 1; transform: translateX(0); max-height: 300px; margin-bottom: 12px; }
    85% { opacity: 0; transform: translateX(60px); max-height: 300px; margin-bottom: 12px; }
    100% { opacity: 0; transform: translateX(60px); max-height: 0; margin-bottom: 0; padding: 0; overflow: hidden; }
  }
  .animate-card-exit { animation: card-exit 2.3s ease-in-out forwards; pointer-events: none; }
  .animate-card-exit-success { animation: card-exit 2.3s ease-in-out forwards; pointer-events: none; }
  .animate-card-exit-success::before {
    content: ''; position: absolute; inset: 0; background: rgba(16, 185, 129, 0.12); border-radius: inherit; z-index: 1;
  }
  .animate-card-exit-reject { animation: card-exit 2.3s ease-in-out forwards; pointer-events: none; }
  .animate-card-exit-reject::before {
    content: ''; position: absolute; inset: 0; background: rgba(239, 68, 68, 0.12); border-radius: inherit; z-index: 1;
  }
  .card-chatting { opacity: 0.55; border-color: #a5b4fc !important; transition: opacity 0.3s, border-color 0.3s; }

  @keyframes indeterminate {
    0% { width: 0%; margin-left: 0%; }
    50% { width: 40%; margin-left: 30%; }
    100% { width: 0%; margin-left: 100%; }
  }
  .animate-indeterminate { animation: indeterminate 1.5s ease-in-out infinite; }
`
if (!document.getElementById('stage-11-5-styles')) {
  styleTag.id = 'stage-11-5-styles'
  document.head.appendChild(styleTag)
}

// ─── OVERVIEW PAGE ───────────────────────────────────────────

function OverviewPage({ overview, prevOverview, onNavigateTable, onNavigateDecisions, recentBatchActivity, recentActivity, sessionStats, onSelectPayment, onNavigateActivity }) {
  const prev = prevOverview || {}
  const { value: animNetRecovered, delta: deltaNet, showDelta: showDeltaNet } = useAnimatedValue(overview?.net_recovered || 0, 800, prev.net_recovered)
  const { value: animRecoveryRate } = useAnimatedValue(overview?.recovery_rate || 0, 1000, prev.recovery_rate)
  const { value: animRoi, delta: deltaRoi, showDelta: showDeltaRoi } = useAnimatedValue(overview?.total_cost > 0 ? Math.round((overview?.net_recovered || 0) / overview.total_cost) : 0, 800, prev.roi)
  const { value: animAtRisk } = useAnimatedValue(overview?.total_at_risk || 0, 800, prev.total_at_risk)

  if (!overview || overview.error) {
    return (
      <div className="text-center py-32">
        <div className="text-6xl mb-4">📊</div>
        <h2 className="text-xl font-semibold text-gray-700 mb-2">No recovery data yet</h2>
      </div>
    )
  }

  const o = overview
  const NAIVE_BASELINE = 2080292

  const causeData = Object.entries(o.cause_distribution || {}).map(([name, value]) => ({
    name: CAUSE_LABELS[name] || name, value, fill: CAUSE_COLORS[name] || '#94a3b8',
  }))

  const actionData = Object.entries(o.action_distribution || {})
    .filter(([k]) => !['scheduled', 'gate_blocked', 'awaiting_decision'].includes(k))
    .map(([name, value]) => ({
      name: name.replace(/_/g, ' '), value, fill: ACTION_COLORS[name] || '#94a3b8',
    }))
    .sort((a, b) => b.value - a.value)

  const funnelData = [
    { label: 'Entered Pipeline', value: o.retryable_count || 299, color: '#3b82f6' },
    { label: 'Resolved Attempt 1', value: o.attempt_distribution?.attempt_1 || 0, color: '#22c55e' },
    { label: 'Resolved Attempt 2', value: o.attempt_distribution?.attempt_2 || 0, color: '#84cc16' },
    { label: 'Resolved Attempt 3', value: o.attempt_distribution?.attempt_3 || 0, color: '#f59e0b' },
    { label: 'Escalated', value: o.attempt_distribution?.escalated || 0, color: '#ef4444' },
  ]

  const bankData = (o.bank_data || []).slice(0, 10).map((b, i) => ({
    name: b.bank, count: b.count, fill: CHART_COLORS[i % CHART_COLORS.length],
    topCause: Object.entries(b.causes || {}).sort((a, b) => b[1] - a[1])[0]?.[0] || '',
  }))

  const roi = o.total_cost > 0 ? Math.round(o.net_recovered / o.total_cost) : 0
  const hasDecisions = o.decisions_pending > 0

  return (
    <div className="space-y-6 pb-12">
      {/* Revenue at Risk — compact hero */}
      <section className="bg-red-50 border border-red-200 rounded-2xl p-4 text-center animate-card-enter">
        <p className="text-sm font-medium text-red-400 uppercase tracking-wider mb-0.5">Revenue at Risk</p>
        <h2 className="text-4xl font-bold text-red-600 mb-1 animate-count">{fmtFull(Math.round(animAtRisk))}</h2>
        <p className="text-red-400 text-sm">{o.total_payments} failed payments this cycle</p>
      </section>

      {/* Session Activity Card */}
      {sessionStats && sessionStats.resolved > 0 && (
        <section className="bg-indigo-50 border border-indigo-200 rounded-xl p-4 animate-card-enter">
          <p className="text-xs font-semibold text-indigo-400 uppercase tracking-wider mb-2">This Session</p>
          <div className="space-y-1">
            <p className="text-sm text-indigo-700 font-medium">✓ {sessionStats.resolved} decision{sessionStats.resolved !== 1 ? 's' : ''} resolved</p>
            {sessionStats.recovered > 0 && (
              <p className="text-sm text-emerald-700 font-medium">✓ {fmtFull(sessionStats.recovered)} recovered from conversations</p>
            )}
            {sessionStats.churned > 0 && (
              <p className="text-sm text-red-600 font-medium">✗ {sessionStats.churned} customer{sessionStats.churned !== 1 ? 's' : ''} churned — {fmtFull(sessionStats.writtenOff)} written off</p>
            )}
            {(sessionStats.initialDecisions != null && sessionStats.initialDecisions - sessionStats.resolved > 0) && (
              <p className="text-sm text-amber-600 font-medium">⏳ {sessionStats.initialDecisions - sessionStats.resolved} decision{(sessionStats.initialDecisions - sessionStats.resolved) !== 1 ? 's' : ''} remaining</p>
            )}
          </div>
        </section>
      )}

      {/* Recovery Results — live numbers */}
      <section>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-5 text-center animate-card-enter">
            <p className="text-sm text-emerald-500 font-medium mb-1">Net Recovered</p>
            <p className="text-4xl font-bold text-emerald-600 animate-count">
              {fmt(Math.round(animNetRecovered))}
              <DeltaBadge delta={deltaNet} showDelta={showDeltaNet} formatter={fmt} />
            </p>
            <p className="text-sm text-emerald-400 mt-1">
              still at risk: {fmtFull(Math.max(0, (o.total_at_risk || 0) - (o.net_recovered || 0)))}
            </p>
          </div>
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-5 text-center animate-card-enter" style={{ animationDelay: '100ms' }}>
            <p className="text-sm text-blue-500 font-medium mb-1">Recovery Rate</p>
            <div className="relative w-20 h-20 mx-auto my-1">
              <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                <circle cx="50" cy="50" r="42" fill="none" stroke="#dbeafe" strokeWidth="8" />
                <circle cx="50" cy="50" r="42" fill="none" stroke="#3b82f6" strokeWidth="8"
                  strokeDasharray={`${animRecoveryRate * 264} 264`} strokeLinecap="round"
                  className="animate-ring" />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-lg font-bold text-blue-600">
                {pct(animRecoveryRate)}
              </span>
            </div>
          </div>
          <div className="bg-purple-50 border border-purple-200 rounded-xl p-5 text-center animate-card-enter" style={{ animationDelay: '200ms' }}>
            <p className="text-sm text-purple-500 font-medium mb-1">ROI</p>
            <p className="text-4xl font-bold text-purple-600 animate-count">
              {Math.round(animRoi).toLocaleString()}x
              <DeltaBadge delta={deltaRoi} showDelta={showDeltaRoi} formatter={(v) => `${Math.round(v)}x`} />
            </p>
            <p className="text-sm text-purple-400 mt-1">{fmtFull(o.total_cost)} spent → {fmt(o.net_recovered)}</p>
          </div>
        </div>
      </section>

      {/* Tier summary */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-center">
          <p className="text-xs text-emerald-500 uppercase tracking-wider mb-1">Tier 1 & 2 — Auto-executed</p>
          <p className="text-2xl font-bold text-emerald-600">{o.auto_executed || 0}</p>
          <p className="text-xs text-emerald-400 mt-1">retries, SMS, calls — all automated</p>
        </div>
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-center">
          <p className="text-xs text-blue-500 uppercase tracking-wider mb-1">Non-retryable</p>
          <p className="text-2xl font-bold text-blue-600">{o.outcome_distribution?.card_update_sent || 0} + {o.outcome_distribution?.mandate_resequenced || 0}</p>
          <p className="text-xs text-blue-400 mt-1">card updates + mandate resequences</p>
        </div>
        {hasDecisions ? (
          <button onClick={onNavigateDecisions}
            className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-center hover:shadow-md transition cursor-pointer">
            <p className="text-xs text-amber-500 uppercase tracking-wider mb-1">Tier 3 — Your Decisions</p>
            <p className="text-2xl font-bold text-amber-600">{o.decisions_pending}</p>
            <p className="text-xs text-amber-400 mt-1">{fmtFull(o.decisions_amount)} needing review</p>
          </button>
        ) : (
          <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 text-center">
            <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">Tier 3 — Decisions</p>
            <p className="text-2xl font-bold text-gray-400">0</p>
            <p className="text-xs text-gray-400 mt-1">all business decisions resolved</p>
          </div>
        )}
      </section>

      {/* Diagnosis & Actions */}
      <section>
        <h3 className="text-lg font-semibold text-gray-700 mb-4">Diagnosis &amp; Actions</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-white border border-gray-200 rounded-xl p-4">
            <h4 className="text-sm font-medium text-gray-500 mb-3">Failure Causes</h4>
            <div className="flex items-center gap-4">
              <DonutChart data={causeData} />
              <div className="flex-1 space-y-1.5">
                {[...causeData].sort((a, b) => b.value - a.value).map(d => {
                  const total = causeData.reduce((s, c) => s + c.value, 0)
                  return (
                    <div key={d.name} className="flex items-center gap-2 text-sm group cursor-pointer hover:bg-gray-50 rounded px-1 -mx-1 py-0.5 transition">
                      <span className="w-2.5 h-2.5 rounded-full flex-shrink-0 group-hover:scale-125 transition-transform" style={{ background: d.fill }} />
                      <span className="text-gray-600 flex-1">{d.name}</span>
                      <span className="font-mono text-gray-800 font-medium">{d.value}</span>
                      <span className="text-[10px] text-gray-400 w-10 text-right opacity-0 group-hover:opacity-100 transition-opacity">{(d.value / total * 100).toFixed(0)}%</span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
          <div className="bg-white border border-gray-200 rounded-xl p-4">
            <h4 className="text-sm font-medium text-gray-500 mb-3">Actions Taken</h4>
            <div className="flex items-center gap-4">
              <DonutChart data={actionData} />
              <div className="flex-1 space-y-1.5">
                {actionData.map(d => {
                  const total = actionData.reduce((s, c) => s + c.value, 0)
                  return (
                    <div key={d.name} className="flex items-center gap-2 text-sm group cursor-pointer hover:bg-gray-50 rounded px-1 -mx-1 py-0.5 transition">
                      <span className="w-2.5 h-2.5 rounded-full flex-shrink-0 group-hover:scale-125 transition-transform" style={{ background: d.fill }} />
                      <span className="text-gray-600 flex-1">{d.name}</span>
                      <span className="font-mono text-gray-800 font-medium">{d.value}</span>
                      <span className="text-[10px] text-gray-400 w-10 text-right opacity-0 group-hover:opacity-100 transition-opacity">{(d.value / total * 100).toFixed(0)}%</span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Recovery Timeline */}
      <section className="bg-white border border-gray-200 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-1">Recovery Timeline</h3>
        <p className="text-sm text-gray-400 mb-4">Cumulative net ₹ recovered over simulated time</p>
        <SvgLineChart data={o.timeline || []} baseline={NAIVE_BASELINE} />
      </section>

      {/* Before vs After */}
      <section className="bg-white border border-gray-200 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-4">Before vs After</h3>
        <div className="grid grid-cols-3 gap-4 items-center">
          <div className="text-center bg-gray-50 rounded-xl p-5 border border-gray-200">
            <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">Naive Retry</p>
            <p className="text-3xl font-bold text-gray-400">{fmt(NAIVE_BASELINE)}</p>
            <p className="text-sm text-gray-400 mt-1">12.6% rate</p>
          </div>
          <div className="text-center">
            {(() => {
              const diff = ((o.net_recovered - NAIVE_BASELINE) / NAIVE_BASELINE) * 100
              const sign = diff >= 0 ? '+' : ''
              return (
                <div className={`${diff >= 0 ? 'bg-emerald-100' : 'bg-red-100'} rounded-full px-4 py-2 inline-block`}>
                  <p className={`text-2xl font-bold ${diff >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>{sign}{diff.toFixed(1)}%</p>
                  <p className={`text-xs ${diff >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                    {diff >= 0 ? 'more' : 'less'} revenue recovered
                  </p>
                </div>
              )
            })()}
          </div>
          <div className="text-center bg-emerald-50 rounded-xl p-5 border border-emerald-200">
            <p className="text-xs text-emerald-500 uppercase tracking-wider mb-1">Smart Recovery</p>
            <p className="text-3xl font-bold text-emerald-600">{fmt(o.net_recovered)}</p>
            <p className="text-sm text-emerald-500 mt-1">{pct(o.recovery_rate)} rate</p>
          </div>
        </div>
      </section>

      {/* Retry Funnel */}
      <section className="bg-white border border-gray-200 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-4">Retry Funnel</h3>
        <div className="space-y-2.5">
          {funnelData.map((d, i) => {
            const maxVal = funnelData[0].value
            const width = Math.max(10, (d.value / maxVal) * 100)
            const dropRate = i > 0 ? ((1 - d.value / funnelData[i - 1].value) * 100).toFixed(1) : null
            return (
              <div key={i} className="flex items-center gap-3 group cursor-pointer">
                <span className="text-sm text-gray-500 w-40 text-right">{d.label}</span>
                <div className="flex-1 h-8 bg-gray-50 rounded-lg overflow-hidden relative">
                  <div className="h-full rounded-lg flex items-center px-3 transition-all duration-300 group-hover:shadow-md"
                    style={{ width: `${width}%`, background: d.color, transform: 'scaleY(1)', transition: 'transform 0.15s, box-shadow 0.15s' }}
                    onMouseEnter={e => e.currentTarget.style.transform = 'scaleY(1.12)'}
                    onMouseLeave={e => e.currentTarget.style.transform = 'scaleY(1)'}>
                    <span className="text-white text-sm font-semibold">{d.value}</span>
                  </div>
                  <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity bg-white/90 px-1.5 py-0.5 rounded">
                    {i === 0 ? `${((d.value / (o.retryable_count + (o.business_decisions_count || 0) + (o.gate_blocked || 0) + (o.non_retryable || 0))) * 100).toFixed(0)}% of total` : `${dropRate}% drop`}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* Bank Intelligence */}
      <section className="bg-white border border-gray-200 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-1">Bank Intelligence</h3>
        <p className="text-sm text-gray-400 mb-4">Top failure-causing banks</p>
        <SvgHBarChart data={bankData} />
      </section>

      {/* Compliance */}
      <section>
        <h3 className="text-lg font-semibold text-gray-700 mb-3">Compliance</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Contact Hours', value: '0 violations', ok: true },
            { label: 'Contact Limits', value: '0 violations', ok: true },
            { label: 'DND Blocks', value: `${o.compliance?.dnd_blocks || 0} blocked`, ok: (o.compliance?.dnd_blocks || 0) <= 5 },
            { label: 'Pre-debit Forced', value: `${o.compliance?.pre_debit_forces || 0} forced to SMS`, ok: true },
          ].map(c => (
            <div key={c.label} className={`rounded-xl p-3 border text-center ${c.ok ? 'bg-emerald-50 border-emerald-200' : 'bg-amber-50 border-amber-200'}`}>
              <div className={`text-lg font-semibold ${c.ok ? 'text-emerald-600' : 'text-amber-600'}`}>
                {c.ok ? '✓' : '!'} {c.value}
              </div>
              <p className="text-xs text-gray-500 mt-0.5">{c.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Needs Attention */}
      <section>
        <h3 className="text-lg font-semibold text-gray-700 mb-3">Needs Attention</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Exhausted Retries', data: o.exceptions?.exhausted, color: 'amber', filter: 'failed_exhausted' },
            { label: 'Escalated', data: o.exceptions?.escalated, color: 'orange', filter: 'escalated' },
            { label: 'Pending Non-Retryable', data: o.exceptions?.pending_nr, color: 'yellow', filter: 'card_update_sent' },
            { label: 'Gate Blocked', data: o.exceptions?.gate_blocked, color: 'red', filter: 'gate_blocked' },
          ].map(e => (
            <button key={e.label} onClick={() => onNavigateTable(e.filter)}
              className={`rounded-xl p-4 border text-left hover:shadow-md transition cursor-pointer
                ${e.color === 'red' ? 'bg-red-50 border-red-200' :
                  e.color === 'orange' ? 'bg-orange-50 border-orange-200' :
                  e.color === 'yellow' ? 'bg-yellow-50 border-yellow-200' :
                  'bg-amber-50 border-amber-200'}`}>
              <p className="text-2xl font-bold text-gray-700">{e.data?.count || 0}</p>
              <p className="text-xs text-gray-500 mt-0.5">{e.label}</p>
              <p className="text-xs font-mono text-gray-400">{fmtFull(e.data?.amount || 0)} at risk</p>
            </button>
          ))}
        </div>
      </section>

      {/* Recent Activity Feed */}
      {recentActivity && recentActivity.length > 0 && (
        <section className="bg-white border border-gray-200 rounded-xl p-5">
          <h3 className="text-lg font-semibold text-gray-700 mb-1">Recent Activity</h3>
          <p className="text-sm text-gray-400 mb-3">Last {Math.min(recentActivity.length, 10)} pipeline events</p>
          <div className="space-y-1.5 max-h-80 overflow-y-auto">
            {recentActivity.slice(0, 10).map((a, i) => (
              <div key={i} className="flex items-center gap-3 py-1.5 px-2 rounded-lg hover:bg-gray-50 transition text-sm animate-feed-in"
                style={{ animationDelay: `${i * 30}ms` }}>
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                  a.outcome === 'recovered' ? 'bg-emerald-500' :
                  a.outcome === 'failed_exhausted' ? 'bg-red-400' :
                  a.outcome === 'escalated' ? 'bg-orange-400' :
                  a.outcome === 'card_update_sent' ? 'bg-blue-400' :
                  a.outcome === 'mandate_resequenced' ? 'bg-cyan-400' :
                  a.outcome === 'merchant_rejected' ? 'bg-red-300' :
                  a.outcome === 'downgrade_offered' ? 'bg-amber-400' :
                  'bg-gray-300'}`} />
                <button onClick={() => onSelectPayment && onSelectPayment(a.payment_id)} className="font-mono text-xs text-blue-600 hover:text-blue-800 w-24 truncate text-left">{a.payment_id}</button>
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                  a.action === 'auto_retry' ? 'bg-emerald-100 text-emerald-700' :
                  a.action?.startsWith('sms') ? 'bg-blue-100 text-blue-700' :
                  a.action?.startsWith('call') ? 'bg-purple-100 text-purple-700' :
                  a.action?.startsWith('decision:') ? 'bg-amber-100 text-amber-700' :
                  'bg-gray-100 text-gray-700'}`}>
                  {a.action?.replace(/_/g, ' ')}
                </span>
                <OutcomeBadge outcome={a.outcome} />
                {a.amount_recovered > 0 && (
                  <span className="text-emerald-600 font-mono text-xs font-medium ml-auto">+{fmtFull(a.amount_recovered)}</span>
                )}
                <span className="text-gray-400 text-[10px] font-mono ml-auto">{a.sim_timestamp?.slice(5, 16)}</span>
              </div>
            ))}
          </div>
          {recentActivity.length > 10 && (
            <button onClick={onNavigateActivity} className="w-full text-center text-sm text-blue-600 hover:text-blue-800 font-medium pt-3 border-t border-gray-100 mt-2 transition">
              View all {recentActivity.length} events in Activity tab →
            </button>
          )}
        </section>
      )}

    </div>
  )
}

// ─── DECISIONS (TIER 3) ─────────────────────────────────────

function DecisionsQueue({ decisions, onApprove, onReject, onSelect, approving, onChat, dismissingIds, chattingPaymentId }) {
  if (!decisions || decisions.length === 0) {
    return (
      <div className="text-center py-32">
        <div className="text-6xl mb-4">✅</div>
        <h2 className="text-xl font-semibold text-gray-700 mb-2">No decisions needed</h2>
        <p className="text-gray-400">All business decisions have been resolved — only mandate cancellations need your input</p>
      </div>
    )
  }

  const totalAtStake = decisions.reduce((s, d) => s + d.amount, 0)

  return (
    <div className="space-y-4">
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
        <div className="flex gap-6 items-center">
          <div>
            <p className="text-xs text-amber-500 uppercase tracking-wider">Business Decisions</p>
            <p className="text-xl font-bold text-amber-700">{decisions.length} mandates cancelled</p>
          </div>
          <div>
            <p className="text-xs text-amber-500 uppercase tracking-wider">At Stake</p>
            <p className="text-xl font-bold text-amber-700">{fmtFull(totalAtStake)}</p>
          </div>
        </div>
        <p className="text-xs text-amber-600 mt-2">These customers cancelled their mandate. You decide: recover the relationship, offer a downgrade, or mark as churned.</p>
      </div>

      <div className="space-y-3">
        {decisions.map((d, idx) => {
          const dismissState = dismissingIds?.[d.payment_id]
          const isChatting = chattingPaymentId === d.payment_id
          const exitClass = dismissState === 'success' ? 'animate-card-exit-success' :
                            dismissState === 'reject' ? 'animate-card-exit-reject' :
                            dismissState ? 'animate-card-exit' : ''
          return (
            <div key={d.payment_id}
              className={`relative bg-white border border-gray-200 rounded-xl p-5 hover:shadow-sm transition
                ${exitClass || 'animate-card-enter'} ${isChatting && !exitClass ? 'card-chatting' : ''}`}
              style={!exitClass ? { animationDelay: `${idx * 60}ms` } : undefined}>
              {isChatting && !exitClass && (
                <span className="absolute top-3 right-3 z-10 text-[11px] font-semibold text-indigo-600 bg-indigo-50 border border-indigo-200 px-2 py-0.5 rounded-full animate-pulse">
                  Chat in progress...
                </span>
              )}
              <div className="flex justify-between items-start mb-3">
                <div>
                  <button onClick={() => onSelect(d.payment_id)} className="text-blue-600 hover:text-blue-800 font-mono text-sm font-medium">
                    {d.payment_id}
                  </button>
                  <p className="text-sm text-gray-500 mt-0.5">
                    {d.customer_id} · {d.bank_name} · {d.payment_method?.replace(/_/g, ' ')} · {d.payment_category}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-xl font-bold text-gray-800">{fmtFull(d.amount)}<span className="text-xs text-gray-400 font-normal">/month</span></p>
                  <TierBadge tier={3} />
                </div>
              </div>

              <div className="bg-gray-50 rounded-lg p-3 mb-3 text-sm text-gray-600">
                {d.recommendation}
              </div>

              <div className="flex gap-2">
                <button onClick={() => { if (onChat) onChat(d.payment_id) }} disabled={approving || !!dismissState || isChatting}
                  className="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:bg-gray-300 text-white text-sm font-medium rounded-lg transition">
                  {isChatting ? 'Chat Active' : 'Start Recovery Chat'}
                </button>
                {d.suggested_downgrade && (
                  <button onClick={() => onApprove(d.payment_id, 'offer_downgrade')} disabled={approving || !!dismissState}
                    className="px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-gray-300 text-white text-sm font-medium rounded-lg transition">
                    Offer ₹{d.suggested_downgrade?.toLocaleString('en-IN')}/mo
                  </button>
                )}
                <button onClick={() => onReject(d.payment_id)} disabled={approving || !!dismissState}
                  className="px-4 py-2 bg-white border border-red-300 hover:bg-red-50 disabled:bg-gray-100 text-red-600 text-sm font-medium rounded-lg transition">
                  Mark Churned
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── SETTINGS ───────────────────────────────────────────────

function SettingsPanel({ config, onSave, saving }) {
  const [form, setForm] = useState(config || {})

  useEffect(() => { if (config) setForm(config) }, [config])

  const handleChange = (key, value) => {
    setForm(f => ({ ...f, [key]: value }))
  }

  const hasChanges = JSON.stringify(form) !== JSON.stringify(config)

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pb-12">
      <div className="space-y-6">
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <h3 className="text-lg font-semibold text-gray-700 mb-1">Merchant Policy</h3>
          <p className="text-sm text-gray-400 mb-6">Configure how the recovery system contacts your customers. Changes apply to the next batch run.</p>

          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-700">SMS Notifications</p>
                <p className="text-xs text-gray-400">Send retry-link SMS to customers</p>
              </div>
              <button onClick={() => handleChange('sms_enabled', !form.sms_enabled)}
                className={`relative w-11 h-6 rounded-full transition ${form.sms_enabled ? 'bg-blue-500' : 'bg-gray-300'}`}>
                <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${form.sms_enabled ? 'left-[22px]' : 'left-0.5'}`} />
              </button>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-700">Phone Calls</p>
                <p className="text-xs text-gray-400">Enable automated recovery calls</p>
              </div>
              <button onClick={() => handleChange('calls_enabled', !form.calls_enabled)}
                className={`relative w-11 h-6 rounded-full transition ${form.calls_enabled ? 'bg-blue-500' : 'bg-gray-300'}`}>
                <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${form.calls_enabled ? 'left-[22px]' : 'left-0.5'}`} />
              </button>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">Min Amount for Calls</label>
              <p className="text-xs text-gray-400 mb-1">Only call for payments above this amount</p>
              <div className="flex items-center gap-2">
                <span className="text-gray-400">₹</span>
                <input type="number" value={form.call_min_amount || 0}
                  onChange={e => handleChange('call_min_amount', parseInt(e.target.value) || 0)}
                  className="border border-gray-200 rounded-lg px-3 py-2 text-sm w-32 focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none" />
              </div>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">Brand Name</label>
              <p className="text-xs text-gray-400 mb-1">Shown in SMS and call scripts</p>
              <input type="text" value={form.brand_name || ''}
                onChange={e => handleChange('brand_name', e.target.value)}
                className="border border-gray-200 rounded-lg px-3 py-2 text-sm w-full focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none" />
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">SMS Template</label>
              <p className="text-xs text-gray-400 mb-1">Variables: {'{service}'}, {'{amount}'}, {'{link}'}</p>
              <textarea value={form.sms_template || ''} rows={2}
                onChange={e => handleChange('sms_template', e.target.value)}
                className="border border-gray-200 rounded-lg px-3 py-2 text-sm w-full focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none resize-none" />
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">Call Tone</label>
              <p className="text-xs text-gray-400 mb-1">Communication style for recovery calls</p>
              <select value={form.call_tone || 'empathetic'}
                onChange={e => handleChange('call_tone', e.target.value)}
                className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none">
                <option value="empathetic">Empathetic</option>
                <option value="professional">Professional</option>
                <option value="urgent">Urgent</option>
              </select>
            </div>

            <div className="border-t border-gray-100 pt-5 mt-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-700">Send to WhatsApp</p>
                  <p className="text-xs text-gray-400">Deliver agent messages via WhatsApp during recovery chats</p>
                </div>
                <button onClick={() => handleChange('whatsapp_enabled', !form.whatsapp_enabled)}
                  className={`relative w-11 h-6 rounded-full transition ${form.whatsapp_enabled ? 'bg-green-500' : 'bg-gray-300'}`}>
                  <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${form.whatsapp_enabled ? 'left-[22px]' : 'left-0.5'}`} />
                </button>
              </div>
            </div>
          </div>

          <div className="mt-6 flex items-center gap-3">
            <button onClick={() => onSave(form)} disabled={saving || !hasChanges}
              className="px-5 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white text-sm font-medium rounded-lg transition shadow-sm">
              {saving ? 'Saving...' : 'Save Policy'}
            </button>
            {!hasChanges && <span className="text-xs text-gray-400">No unsaved changes</span>}
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 text-sm text-gray-500">
          <h4 className="font-medium text-gray-700 mb-2">How Tiered Approval Works</h4>
          <div className="space-y-2">
            <div className="flex gap-2 items-start">
              <TierBadge tier={1} />
              <p><span className="font-medium text-gray-700">Automated</span> — retries, constraint enforcement, timing optimization. No merchant input needed.</p>
            </div>
            <div className="flex gap-2 items-start">
              <TierBadge tier={2} />
              <p><span className="font-medium text-gray-700">Policy-driven</span> — your settings above control SMS, calls, and contact preferences. Configure once, applied to all.</p>
            </div>
            <div className="flex gap-2 items-start">
              <TierBadge tier={3} />
              <p><span className="font-medium text-gray-700">Business decisions</span> — mandate cancellations need your judgment. Appears in the Decisions tab.</p>
            </div>
          </div>
        </div>

        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-5 text-sm text-gray-600">
          <h4 className="font-medium text-emerald-800 mb-2">What Gets Recovered</h4>
          <div className="space-y-1.5">
            <p><span className="font-medium text-emerald-700">Insufficient funds</span> — auto-retried at optimal times based on salary/deposit patterns.</p>
            <p><span className="font-medium text-emerald-700">Bank outages</span> — detected via BIN clustering, retried after outage window passes.</p>
            <p><span className="font-medium text-emerald-700">AFA stuck</span> — SMS/call nudges to complete additional factor authentication.</p>
            <p><span className="font-medium text-emerald-700">Card expired</span> — card-update links sent to customers.</p>
            <p><span className="font-medium text-emerald-700">Mandate issues</span> — escalated for merchant decision (Tier 3).</p>
          </div>
        </div>

        <div className="bg-blue-50 border border-blue-200 rounded-xl p-5 text-sm text-gray-600">
          <h4 className="font-medium text-blue-800 mb-2">Compliance Built In</h4>
          <div className="space-y-1.5">
            <p><span className="font-medium text-blue-700">RBI mandate rules</span> — pre-debit notifications enforced, AFA thresholds respected.</p>
            <p><span className="font-medium text-blue-700">Retry limits</span> — max 3 retries per payment, exponential backoff between attempts.</p>
            <p><span className="font-medium text-blue-700">Audit trail</span> — every action logged with timestamp, tier, and outcome for compliance review.</p>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── ACTIVITY FEED ──────────────────────────────────────────

function ActivityFeed({ activity, onSelectPayment }) {
  const [page, setPage] = useState(0)
  const [selectedDate, setSelectedDate] = useState(null)
  const perPage = 30

  if (!activity || activity.length === 0) {
    return (
      <div className="text-center py-32">
        <div className="text-6xl mb-4">📋</div>
        <h2 className="text-xl font-semibold text-gray-700 mb-2">No activity yet</h2>
        <p className="text-gray-400">Run a batch to see the activity feed</p>
      </div>
    )
  }

  const dateMap = {}
  activity.forEach(a => {
    const day = a.sim_timestamp?.slice(0, 10)
    if (day) {
      if (!dateMap[day]) dateMap[day] = []
      dateMap[day].push(a)
    }
  })
  const sortedDates = Object.keys(dateMap).sort()

  const fmtDate = (d) => {
    const [, m, day] = d.split('-')
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    return `${months[parseInt(m) - 1]} ${parseInt(day)}`
  }

  const filtered = selectedDate ? (dateMap[selectedDate] || []) : activity
  const succeeded = filtered.filter(a => a.amount_recovered > 0)
  const totalRecovered = succeeded.reduce((s, a) => s + (a.amount_recovered || 0), 0)

  const totalPages = Math.ceil(filtered.length / perPage)
  const start = page * perPage
  const end = Math.min(start + perPage, filtered.length)
  const pageItems = filtered.slice(start, end)

  const selectDate = (d) => {
    setSelectedDate(d)
    setPage(0)
  }

  return (
    <div className="space-y-2 pb-12">
      <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
        <button onClick={() => selectDate(null)}
          className={`flex-shrink-0 px-3 py-1.5 rounded-full text-sm font-medium border transition ${
            selectedDate === null
              ? 'bg-blue-600 text-white border-blue-600'
              : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300 hover:bg-blue-50'
          }`}>
          All <span className={`ml-1 text-xs ${selectedDate === null ? 'text-blue-200' : 'text-gray-400'}`}>{activity.length}</span>
        </button>
        {sortedDates.map(d => (
          <button key={d} onClick={() => selectDate(d)}
            className={`flex-shrink-0 px-3 py-1.5 rounded-full text-sm font-medium border transition ${
              selectedDate === d
                ? 'bg-blue-600 text-white border-blue-600'
                : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300 hover:bg-blue-50'
            }`}>
            {fmtDate(d)} <span className={`ml-1 text-xs ${selectedDate === d ? 'text-blue-200' : 'text-gray-400'}`}>{dateMap[d].length}</span>
          </button>
        ))}
      </div>

      <div className="text-sm text-gray-500 pb-1">
        <span className="font-medium text-gray-700">{selectedDate ? fmtDate(selectedDate) : 'All days'}</span>
        {' — '}
        {filtered.length} events, {succeeded.length} succeeded, <span className="text-emerald-600 font-medium">{fmtFull(totalRecovered)}</span> recovered
      </div>

      <div className="flex items-center justify-between mb-1">
        <p className="text-sm text-gray-400">Showing {filtered.length > 0 ? start + 1 : 0}–{end} of {filtered.length} events</p>
        {totalPages > 1 && (
          <div className="flex items-center gap-2">
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
              className="px-3 py-1.5 text-sm font-medium rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition">
              Previous
            </button>
            <span className="text-sm text-gray-500">Page {page + 1} of {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
              className="px-3 py-1.5 text-sm font-medium rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition">
              Next
            </button>
          </div>
        )}
      </div>
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <table className="w-full text-[14px]">
          <thead>
            <tr className="bg-gray-50 text-left text-gray-500 border-b border-gray-200">
              <th className="px-4 py-3.5 font-semibold text-[13px]">Payment</th>
              <th className="px-4 py-3.5 font-semibold text-[13px]">Action</th>
              <th className="px-4 py-3.5 font-semibold text-[13px]">Outcome</th>
              <th className="px-4 py-3.5 font-semibold text-[13px]">Amount</th>
              <th className="px-4 py-3.5 font-semibold text-[13px]">Recovered</th>
              <th className="px-4 py-3.5 font-semibold text-[13px]">Cause</th>
              <th className="px-4 py-3.5 font-semibold text-[13px]">Time</th>
            </tr>
          </thead>
          <tbody>
            {pageItems.map((a, i) => (
              <tr key={start + i} className="border-b border-gray-100 hover:bg-blue-50/30 transition">
                <td className="px-4 py-3.5">
                  <button onClick={() => onSelectPayment && onSelectPayment(a.payment_id)} className="text-blue-600 hover:text-blue-800 font-mono text-[13px] font-medium">
                    {a.payment_id}
                  </button>
                </td>
                <td className="px-4 py-3.5">
                  <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium
                    ${a.action === 'auto_retry' ? 'bg-emerald-100 text-emerald-700' :
                      a.action?.startsWith('sms') ? 'bg-blue-100 text-blue-700' :
                      a.action?.startsWith('call') ? 'bg-purple-100 text-purple-700' :
                      a.action?.startsWith('decision:') ? 'bg-amber-100 text-amber-700' :
                      'bg-gray-100 text-gray-700'}`}>
                    {a.action?.replace(/_/g, ' ')}
                  </span>
                </td>
                <td className="px-4 py-3.5"><OutcomeBadge outcome={a.outcome} /></td>
                <td className="px-4 py-3.5 font-mono text-gray-700">{fmtFull(a.amount)}</td>
                <td className="px-4 py-3.5 font-mono">
                  {a.amount_recovered > 0
                    ? <span className="text-emerald-600">+{fmtFull(a.amount_recovered)}</span>
                    : <span className="text-gray-400">₹0</span>}
                </td>
                <td className="px-4 py-3.5 text-[13px] text-gray-500">{a.cause?.replace(/_/g, ' ')}</td>
                <td className="px-4 py-3.5 text-[13px] text-gray-400 font-mono">{a.sim_timestamp?.slice(0, 16)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <p className="text-xs text-gray-400">Showing {start + 1}–{end} of {filtered.length}</p>
          <div className="flex items-center gap-2">
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
              className="px-3 py-1.5 text-sm font-medium rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition">
              Previous
            </button>
            <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
              className="px-3 py-1.5 text-sm font-medium rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition">
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── PAYMENTS TABLE ──────────────────────────────────────────

function PaymentsTable({ payments, onSelect, initialOutcomeFilter }) {
  const [filter, setFilter] = useState({ status: '', cause: '', method: '', outcome: initialOutcomeFilter || '' })
  const [sortBy, setSortBy] = useState('amount')
  const [sortDir, setSortDir] = useState('desc')

  useEffect(() => {
    if (initialOutcomeFilter) setFilter(f => ({ ...f, outcome: initialOutcomeFilter }))
  }, [initialOutcomeFilter])

  const filtered = (payments || []).filter(p => {
    if (filter.status && p.status !== filter.status) return false
    if (filter.cause && p.diagnosed_cause !== filter.cause) return false
    if (filter.method && p.payment_method !== filter.method) return false
    if (filter.outcome && p.final_outcome !== filter.outcome) return false
    return true
  })

  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortBy], bv = b[sortBy]
    if (typeof av === 'number' && typeof bv === 'number') return sortDir === 'desc' ? bv - av : av - bv
    return sortDir === 'desc' ? String(bv).localeCompare(String(av)) : String(av).localeCompare(String(bv))
  })

  const toggleSort = (col) => {
    if (sortBy === col) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortBy(col); setSortDir('desc') }
  }

  const causes = [...new Set(payments?.map(p => p.diagnosed_cause) || [])].sort()
  const methods = [...new Set(payments?.map(p => p.payment_method) || [])].sort()
  const statuses = [...new Set(payments?.map(p => p.status) || [])]
  const outcomes = [...new Set(payments?.map(p => p.final_outcome).filter(Boolean) || [])].sort()

  return (
    <div className="space-y-4">
      <div className="flex gap-3 flex-wrap items-center">
        {[
          { key: 'status', label: 'Status', options: statuses },
          { key: 'cause', label: 'Cause', options: causes },
          { key: 'method', label: 'Method', options: methods },
          { key: 'outcome', label: 'Outcome', options: outcomes },
        ].map(f => (
          <select key={f.key} value={filter[f.key]}
            onChange={e => setFilter(prev => ({ ...prev, [f.key]: e.target.value }))}
            className="bg-white border border-gray-200 text-sm rounded-lg px-3 py-1.5 text-gray-600 focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none">
            <option value="">All {f.label.toLowerCase().endsWith('s') ? f.label.toLowerCase() + 'es' : f.label.toLowerCase() + 's'}</option>
            {f.options.map(o => <option key={o} value={o}>{o?.replace(/_/g, ' ')}</option>)}
          </select>
        ))}
        {(filter.status || filter.cause || filter.method || filter.outcome) && (
          <button onClick={() => setFilter({ status: '', cause: '', method: '', outcome: '' })}
            className="text-xs text-blue-500 hover:text-blue-700">Clear filters</button>
        )}
        <span className="text-xs text-gray-400 ml-auto">{sorted.length} of {payments?.length || 0}</span>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-[14px]">
            <thead>
              <tr className="bg-gray-50 text-left text-gray-500 border-b border-gray-200">
                {[
                  ['payment_id', 'Payment ID'],
                  ['amount', 'Amount'],
                  ['diagnosed_cause', 'Cause'],
                  ['payment_method', 'Method'],
                  ['status', 'Status'],
                  ['final_outcome', 'Outcome'],
                  ['net_recovered', 'Net'],
                  ['total_attempts', '#'],
                ].map(([key, label]) => (
                  <th key={key} className="px-4 py-3.5 font-semibold text-[13px] cursor-pointer hover:text-gray-700" onClick={() => toggleSort(key)}>
                    {label} {sortBy === key ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.slice(0, 100).map(p => (
                <tr key={p.payment_id} className="border-b border-gray-100 hover:bg-blue-50/30 transition">
                  <td className="px-4 py-3.5">
                    <button onClick={() => onSelect(p.payment_id)} className="text-blue-600 hover:text-blue-800 font-mono text-[13px] font-medium">
                      {p.payment_id}
                    </button>
                  </td>
                  <td className="px-4 py-3.5 font-mono font-medium text-gray-800">{fmtFull(p.amount)}</td>
                  <td className="px-4 py-3.5 text-[13px] text-gray-600">{p.diagnosed_cause?.replace(/_/g, ' ')}</td>
                  <td className="px-4 py-3.5 text-[13px] text-gray-500">{p.payment_method?.replace(/_/g, ' ')}</td>
                  <td className="px-4 py-3.5"><StatusBadge status={p.status} /></td>
                  <td className="px-4 py-3.5"><OutcomeBadge outcome={p.final_outcome} /></td>
                  <td className="px-4 py-3.5 font-mono text-[13px] font-medium">
                    {p.net_recovered > 0
                      ? <span className="text-emerald-600">+{fmtFull(p.net_recovered)}</span>
                      : p.net_recovered < 0
                      ? <span className="text-red-500">{fmtFull(p.net_recovered)}</span>
                      : <span className="text-gray-400">₹0</span>}
                  </td>
                  <td className="px-4 py-3.5 text-center text-gray-500">{p.total_attempts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {sorted.length > 100 && (
          <p className="text-xs text-gray-400 text-center py-2 border-t border-gray-100">Showing first 100 of {sorted.length}</p>
        )}
      </div>
    </div>
  )
}

// ─── DETAIL VIEW ─────────────────────────────────────────────

function DetailView({ detail, onBack, onApprove, onReject }) {
  if (!detail) return null
  const { payment, diagnosis, status, final_outcome, amount_recovered, action_cost, net_recovered, attempt_history, events, business_decision, tier } = detail

  return (
    <div className="space-y-6 pb-12">
      <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-800 font-medium">&larr; Back to all payments</button>

      <div className="bg-white border border-gray-200 rounded-xl p-5 flex justify-between items-start">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-bold text-gray-800 font-mono">{payment.payment_id}</h2>
            <TierBadge tier={tier} />
          </div>
          <p className="text-sm text-gray-500 mt-1">{payment.customer_id} · {payment.bank_name} · {payment.payment_method.replace(/_/g, ' ')} · {payment.payment_category}</p>
        </div>
        <div className="text-right">
          <p className="text-3xl font-bold text-gray-800">{fmtFull(payment.amount)}</p>
          <div className="mt-1"><StatusBadge status={status} /></div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs text-gray-400 uppercase tracking-wider">Cause</p>
          <p className="text-lg font-semibold text-gray-800 mt-1">{diagnosis.cause?.replace(/_/g, ' ')}</p>
          <p className="text-xs text-gray-400">{(diagnosis.confidence * 100).toFixed(0)}% confidence</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs text-gray-400 uppercase tracking-wider">Outcome</p>
          <p className="text-lg font-semibold text-gray-800 mt-1">{(final_outcome || status)?.replace(/_/g, ' ')}</p>
        </div>
        <div className={`border rounded-xl p-4 ${amount_recovered > 0 ? 'bg-emerald-50 border-emerald-200' : 'bg-white border-gray-200'}`}>
          <p className="text-xs text-gray-400 uppercase tracking-wider">Recovered</p>
          <p className={`text-lg font-semibold mt-1 ${amount_recovered > 0 ? 'text-emerald-600' : 'text-gray-800'}`}>{fmtFull(amount_recovered)}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs text-gray-400 uppercase tracking-wider">Net</p>
          <p className={`text-lg font-semibold mt-1 ${net_recovered > 0 ? 'text-emerald-600' : net_recovered < 0 ? 'text-red-500' : 'text-gray-800'}`}>
            {fmtFull(net_recovered)}
          </p>
          <p className="text-xs text-gray-400">cost: {fmtFull(action_cost)}</p>
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-4">
        <div className="grid grid-cols-2 gap-y-2 text-sm">
          <div><span className="text-gray-400">Failure Code:</span> <span className="font-mono text-gray-700">{payment.failure_reason_code}</span></div>
          <div><span className="text-gray-400">Failure Time:</span> <span className="font-mono text-gray-700 text-xs">{payment.failure_timestamp}</span></div>
          <div><span className="text-gray-400">Category:</span> <span className="text-gray-700">{payment.payment_category}</span></div>
        </div>
      </div>

      {business_decision && business_decision.status === 'pending' && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-amber-700 mb-2">Business Decision Required <TierBadge tier={3} /></h3>
          <p className="text-sm text-gray-600 mb-3">{business_decision.recommendation}</p>
          <div className="flex gap-2">
            <button onClick={() => onApprove(payment.payment_id, 'approve_conversation')}
              className="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-medium rounded-lg transition">
              Recovery Conversation
            </button>
            {business_decision.suggested_downgrade && (
              <button onClick={() => onApprove(payment.payment_id, 'offer_downgrade')}
                className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium rounded-lg transition">
                Offer ₹{business_decision.suggested_downgrade?.toLocaleString('en-IN')}/mo
              </button>
            )}
            <button onClick={() => onReject(payment.payment_id)}
              className="px-4 py-2 bg-white border border-red-300 hover:bg-red-50 text-red-600 text-sm font-medium rounded-lg transition">
              Mark Churned
            </button>
          </div>
        </div>
      )}

      {attempt_history && attempt_history.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">Attempt Timeline</h3>
          <div className="relative ml-4">
            <div className="absolute left-2.5 top-1 bottom-1 w-0.5 bg-gray-200" />
            {attempt_history.map((a, i) => {
              const isSuccess = a.outcome === 'success'
              return (
                <div key={i} className="relative flex gap-4 pb-6 last:pb-0">
                  <div className={`relative z-10 w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 mt-0.5
                    ${isSuccess ? 'bg-emerald-500 border-emerald-500' : 'bg-red-400 border-red-400'}`}>
                    <span className="text-white text-[10px] font-bold">{isSuccess ? '✓' : '✗'}</span>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-gray-700">Attempt {a.attempt}</span>
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium
                        ${a.action === 'auto_retry' ? 'bg-emerald-100 text-emerald-700' :
                          a.action === 'sms_then_retry' ? 'bg-blue-100 text-blue-700' :
                          a.action === 'call_then_retry' ? 'bg-purple-100 text-purple-700' :
                          'bg-gray-100 text-gray-700'}`}>
                        {a.action?.replace(/_/g, ' ')}
                      </span>
                      <span className={`text-xs font-medium ${isSuccess ? 'text-emerald-600' : 'text-red-500'}`}>
                        {a.outcome}
                      </span>
                    </div>
                    <div className="text-xs text-gray-400 mt-1 font-mono">{a.time}</div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      Cost: ₹{a.cost?.toFixed(0)}
                      {a.recovered > 0 && <span className="text-emerald-600 ml-2">Recovered: {fmtFull(a.recovered)}</span>}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {events && events.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">Audit Events ({events.length})</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-gray-400 border-b border-gray-200">
                  <th className="pb-2 pr-3 font-medium">Type</th>
                  <th className="pb-2 pr-3 font-medium">Action</th>
                  <th className="pb-2 pr-3 font-medium">Tier</th>
                  <th className="pb-2 pr-3 font-medium">Success</th>
                  <th className="pb-2 pr-3 font-medium">Recovered</th>
                  <th className="pb-2 pr-3 font-medium">Cost</th>
                  <th className="pb-2 font-medium">Sim Time</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e, i) => (
                  <tr key={i} className="border-b border-gray-50">
                    <td className="py-1.5 pr-3 text-gray-500">{e.event_type}</td>
                    <td className="py-1.5 pr-3 text-gray-700">{e.action_type}</td>
                    <td className="py-1.5 pr-3"><TierBadge tier={e.tier} /></td>
                    <td className="py-1.5 pr-3">
                      {e.outcome_success ? <span className="text-emerald-600 font-medium">yes</span> : <span className="text-gray-400">no</span>}
                    </td>
                    <td className="py-1.5 pr-3 font-mono text-gray-700">{fmtFull(e.amount_recovered)}</td>
                    <td className="py-1.5 pr-3 font-mono text-gray-700">{fmtFull(e.action_cost)}</td>
                    <td className="py-1.5 font-mono text-gray-400">{e.sim_timestamp?.slice(0, 16)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── APP ─────────────────────────────────────────────────────

// ─── CHAT WIDGET ──────────────────────────────────────────

function ChatWidget({ paymentId, onClose, onChatComplete, whatsappEnabled }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [ended, setEnded] = useState(false)
  const [state, setState] = useState(null)
  const [chatError, setChatError] = useState(null)
  const [lastFailedMsg, setLastFailedMsg] = useState(null)
  const messagesEndRef = useRef(null)

  useEffect(() => {
    if (!paymentId) return
    setMessages([])
    setEnded(false)
    setState(null)
    setChatError(null)
    setLastFailedMsg(null)
    fetch(`${API}/escalate/${paymentId}`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (data.agent_message) {
          setMessages([{ role: 'agent', text: data.agent_message, whatsapp: data.whatsapp_sent }])
          setState(data.state)
        }
      })
      .catch(() => setChatError('Failed to start conversation'))
  }, [paymentId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading, ended])

  const send = async (overrideMsg) => {
    const msg = overrideMsg || input.trim()
    if (!msg || ended) return
    setInput('')
    setChatError(null)
    setLastFailedMsg(null)
    if (!overrideMsg) setMessages(prev => [...prev, { role: 'customer', text: msg }])
    setLoading(true)
    try {
      const res = await fetch(`${API}/escalate/${paymentId}/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      })
      const data = await res.json()
      if (data.error) {
        setChatError(data.message || 'Conversation error')
        setLastFailedMsg(msg)
      } else if (data.agent_message) {
        setMessages(prev => [...prev, { role: 'agent', text: data.agent_message, whatsapp: data.whatsapp_sent }])
        setState(data.state)
        if (data.conversation_ended) setEnded(true)
      }
    } catch {
      setChatError('Network error — check backend')
      setLastFailedMsg(msg)
    }
    setLoading(false)
  }

  const handleClose = () => {
    if (ended && onChatComplete) {
      onChatComplete(paymentId, state?.outcome)
    }
    onClose()
  }

  if (!paymentId) return null

  const outcomeConfig = {
    promise_to_pay: { bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', icon: '✓', label: 'Customer agreed to pay' },
    interested_in_downgrade: { bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-700', icon: '↓', label: 'Interested in downgrade' },
    wants_callback: { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', icon: '↻', label: 'Callback requested' },
    needs_human_escalation: { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', icon: '⚠', label: 'Needs human escalation' },
    refused: { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', icon: '✗', label: 'Customer refused' },
  }

  return (
    <div className="fixed bottom-6 right-6 w-96 bg-white rounded-2xl shadow-2xl border border-gray-200 flex flex-col z-50" style={{ maxHeight: '520px' }}>
      <div className="bg-emerald-600 text-white px-4 py-3 rounded-t-2xl flex justify-between items-center">
        <div>
          <p className="text-sm font-semibold">Recovery Chat</p>
          <p className="text-xs opacity-80">{paymentId}</p>
        </div>
        <div className="flex items-center gap-2">
          {state?.scenario && state.scenario !== 'unknown' && (
            <span className="text-xs bg-white/20 px-2 py-0.5 rounded-full">{state.scenario.replace(/_/g, ' ')}</span>
          )}
          <button onClick={handleClose} className="text-white/70 hover:text-white text-lg leading-none">&times;</button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3" style={{ minHeight: '200px', maxHeight: '340px' }}>
        {messages.map((m, i) => (
          <div key={i} className={`flex flex-col ${m.role === 'agent' ? 'items-start' : 'items-end'}`}>
            <div className={`max-w-[80%] px-3 py-2 rounded-2xl text-sm ${
              m.role === 'agent'
                ? 'bg-gray-100 text-gray-800 rounded-bl-sm'
                : 'bg-emerald-500 text-white rounded-br-sm'
            }`}>
              {m.text}
            </div>
            {m.role === 'agent' && m.whatsapp && (
              <span className="flex items-center gap-1 mt-0.5 ml-1 text-[10px] text-green-600">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/><path d="M12 2C6.477 2 2 6.477 2 12c0 1.89.525 3.66 1.438 5.168L2 22l4.832-1.438A9.955 9.955 0 0012 22c5.523 0 10-4.477 10-10S17.523 2 12 2zm0 18a8 8 0 01-4.108-1.135l-.288-.171-2.988.783.796-2.916-.187-.299A8 8 0 1112 20z"/></svg>
                Sent via WhatsApp
              </span>
            )}
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 px-3 py-2 rounded-2xl rounded-bl-sm text-sm text-gray-400">typing...</div>
          </div>
        )}
        {chatError && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-center">
            <p className="text-sm text-red-600 mb-2">{chatError}</p>
            {lastFailedMsg && (
              <button onClick={() => send(lastFailedMsg)}
                className="px-3 py-1 bg-red-100 hover:bg-red-200 text-red-700 text-xs font-medium rounded-lg transition">
                Retry
              </button>
            )}
          </div>
        )}
        {ended && state?.outcome && (() => {
          const oc = outcomeConfig[state.outcome] || outcomeConfig.refused
          return (
            <div className={`${oc.bg} ${oc.border} border rounded-xl p-4 text-center animate-card-enter`}>
              <div className={`text-2xl mb-1`}>{oc.icon}</div>
              <p className={`text-sm font-semibold ${oc.text}`}>{oc.label}</p>
              <p className="text-xs text-gray-500 mt-1">{state.outcome.replace(/_/g, ' ')}</p>
              <button onClick={handleClose}
                className={`mt-3 px-4 py-1.5 ${oc.bg} ${oc.border} border ${oc.text} text-sm font-medium rounded-lg hover:shadow-sm transition`}>
                Close
              </button>
            </div>
          )
        })()}
        <div ref={messagesEndRef} />
      </div>

      {!ended && !chatError && (
        <div className="border-t border-gray-100 p-3 flex gap-2">
          <input value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && send()}
            placeholder="Customer's response..."
            className="flex-1 px-3 py-2 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent" />
          <button onClick={() => send()} disabled={loading || !input.trim()}
            className="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:bg-gray-300 text-white text-sm font-medium rounded-xl transition">
            Send
          </button>
        </div>
      )}
    </div>
  )
}

// ─── TEST ENTRY ─────────────────────────────────────────────

function TestEntry({ onResult }) {
  const [form, setForm] = useState({
    amount: 5000,
    payment_method: 'upi_autopay',
    payment_category: 'subscription',
    bank_name: 'HDFC',
    failure_reason_code: '04',
    customer_prior_success_count: 5,
    customer_prior_failure_count: 0,
    amount_above_afa_threshold: false,
    pre_debit_notification_sent: true,
  })
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)
  const [visibleSteps, setVisibleSteps] = useState(0)

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const submit = async () => {
    setSubmitting(true)
    setResult(null)
    setVisibleSteps(0)
    try {
      const res = await fetch(`${API}/test-payment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      const data = await res.json()
      setResult(data)
      if (data.steps) {
        for (let i = 0; i < data.steps.length; i++) {
          await new Promise(r => setTimeout(r, 600))
          setVisibleSteps(i + 1)
        }
      }
      if (onResult) onResult(data)
    } catch (e) {
      setResult({ error: e.message })
    }
    setSubmitting(false)
  }

  const fields = [
    { key: 'amount', label: 'Amount (₹)', type: 'number' },
    { key: 'payment_method', label: 'Payment Method', type: 'select', options: ['upi_autopay', 'enach', 'card_auto_debit'] },
    { key: 'payment_category', label: 'Category', type: 'select', options: ['subscription', 'emi', 'sip', 'insurance', 'cc_bill'] },
    { key: 'bank_name', label: 'Bank', type: 'select', options: ['HDFC', 'ICICI', 'SBI', 'Axis', 'Kotak', 'PNB', 'Yes Bank', 'IndusInd', 'Bank of Baroda', 'Bank of India', 'Canara', 'IDBI', 'Union Bank'] },
    { key: 'failure_reason_code', label: 'Failure Reason Code', type: 'select', options: ['04', '14', '59', '61', 'afa_pending', 'card_expired', 'timeout', 'unknown'] },
    { key: 'customer_prior_success_count', label: 'Prior Successes', type: 'number' },
    { key: 'customer_prior_failure_count', label: 'Prior Failures', type: 'number' },
    { key: 'amount_above_afa_threshold', label: 'Above AFA Threshold', type: 'toggle' },
    { key: 'pre_debit_notification_sent', label: 'Pre-debit Notification Sent', type: 'toggle' },
  ]

  const stepIcon = (phase) => {
    if (phase === 'diagnosis') return '🔍'
    if (phase === 'gate') return '🛡️'
    if (phase === 'bandit') return '🎰'
    if (phase === 'decision') return '⚖️'
    if (phase === 'action') return '⚡'
    if (phase === 'retry') return '🔄'
    return '→'
  }

  const outcomeColor = (outcome) => {
    if (outcome === 'recovered') return 'text-emerald-600'
    if (outcome === 'decision_pending') return 'text-amber-600'
    if (outcome === 'gate_blocked') return 'text-red-600'
    if (outcome === 'failed_exhausted') return 'text-red-500'
    return 'text-gray-700'
  }

  return (
    <div className="space-y-6 pb-12">
      <div className="bg-white border border-gray-200 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-1">Test a Payment</h3>
        <p className="text-sm text-gray-400 mb-5">Enter a payment scenario to see how the AI recovery pipeline processes it end-to-end</p>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {fields.map(f => (
            <div key={f.key}>
              <label className="block text-xs font-medium text-gray-500 mb-1">{f.label}</label>
              {f.type === 'select' ? (
                <select value={form[f.key]} onChange={e => set(f.key, e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none">
                  {f.options.map(o => <option key={o} value={o}>{o.replace(/_/g, ' ')}</option>)}
                </select>
              ) : f.type === 'number' ? (
                <input type="number" value={form[f.key]} onChange={e => set(f.key, Number(e.target.value))}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none font-mono" />
              ) : f.type === 'toggle' ? (
                <button onClick={() => set(f.key, !form[f.key])}
                  className={`w-12 h-6 rounded-full transition-colors ${form[f.key] ? 'bg-blue-500' : 'bg-gray-300'} relative`}>
                  <span className={`block w-5 h-5 rounded-full bg-white shadow absolute top-0.5 transition-transform ${form[f.key] ? 'translate-x-6' : 'translate-x-0.5'}`} />
                </button>
              ) : null}
            </div>
          ))}
        </div>

        <button onClick={submit} disabled={submitting}
          className="mt-6 px-6 py-2.5 bg-blue-600 text-white rounded-lg font-medium text-sm hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2">
          {submitting ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Processing...
            </>
          ) : 'Run Through Pipeline'}
        </button>
      </div>

      {result && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 animate-card-enter">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-700">Pipeline Result</h3>
              <p className="text-sm font-mono text-gray-400">{result.payment_id}</p>
            </div>
            <div className="text-right">
              <p className={`text-lg font-bold ${outcomeColor(result.outcome)}`}>
                {result.outcome?.replace(/_/g, ' ')}
              </p>
              <p className="text-xs text-gray-400">Tier {result.tier}</p>
            </div>
          </div>

          {result.amount_recovered > 0 && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3 mb-4 text-center">
              <p className="text-sm text-emerald-500">Amount Recovered</p>
              <p className="text-2xl font-bold text-emerald-600">{fmtFull(result.amount_recovered)}</p>
            </div>
          )}

          {result.steps && (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Pipeline Steps</p>
              {result.steps.map((s, i) => (
                <div key={i} className={`flex items-start gap-3 py-2 px-3 rounded-lg border transition-all duration-300
                  ${i < visibleSteps ? 'opacity-100 translate-y-0 border-gray-100 bg-gray-50' : 'opacity-0 translate-y-2 border-transparent'}`}
                  style={{ transitionDelay: `${i * 50}ms` }}>
                  <span className="text-lg flex-shrink-0 mt-0.5">{stepIcon(s.phase)}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-gray-400 uppercase">{s.phase}</p>
                    <p className="text-sm text-gray-700">{s.detail}</p>
                    {s.confidence != null && (
                      <div className="mt-1 flex items-center gap-2">
                        <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                          <div className="h-full bg-blue-500 rounded-full" style={{ width: `${s.confidence * 100}%` }} />
                        </div>
                        <span className="text-[10px] text-gray-400">{(s.confidence * 100).toFixed(0)}% confidence</span>
                      </div>
                    )}
                    {s.amount_recovered > 0 && (
                      <span className="text-xs text-emerald-600 font-semibold">+{fmtFull(s.amount_recovered)}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {result.decision && (
            <div className="mt-4 bg-amber-50 border border-amber-200 rounded-lg p-3">
              <p className="text-xs font-semibold text-amber-500 uppercase mb-1">Business Decision Queued</p>
              <p className="text-sm text-amber-700">{result.decision.recommendation}</p>
              <p className="text-xs text-amber-400 mt-1">Go to the Decisions tab to review and act on this</p>
            </div>
          )}

          {result.error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3">
              <p className="text-sm text-red-600">{result.error}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function SetupForm({ config, onSave, saving, onSkip }) {
  const [form, setForm] = useState(config || {})
  useEffect(() => { if (config) setForm(config) }, [config])
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const Toggle = ({ label, desc, field }) => (
    <div className="flex items-center justify-between py-2">
      <div>
        <p className="text-sm font-medium text-gray-700">{label}</p>
        <p className="text-xs text-gray-400">{desc}</p>
      </div>
      <button onClick={() => set(field, !form[field])}
        className={`relative w-11 h-6 rounded-full transition ${form[field] ? 'bg-blue-500' : 'bg-gray-300'}`}>
        <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${form[field] ? 'left-[22px]' : 'left-0.5'}`} />
      </button>
    </div>
  )

  return (
    <div className="space-y-4">
      <Toggle label="SMS Notifications" desc="Send retry-link SMS to customers" field="sms_enabled" />
      <Toggle label="Phone Calls" desc="Enable automated recovery calls" field="calls_enabled" />

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-sm font-medium text-gray-700">Min Amount for Calls</label>
          <div className="flex items-center gap-1 mt-1">
            <span className="text-gray-400 text-sm">₹</span>
            <input type="number" value={form.call_min_amount || 0}
              onChange={e => set('call_min_amount', parseInt(e.target.value) || 0)}
              className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-full focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none" />
          </div>
        </div>
        <div>
          <label className="text-sm font-medium text-gray-700">Call Tone</label>
          <select value={form.call_tone || 'empathetic'}
            onChange={e => set('call_tone', e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-full mt-1 focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none">
            <option value="empathetic">Empathetic</option>
            <option value="professional">Professional</option>
            <option value="urgent">Urgent</option>
          </select>
        </div>
      </div>

      <div>
        <label className="text-sm font-medium text-gray-700">Brand Name</label>
        <input type="text" value={form.brand_name || ''}
          onChange={e => set('brand_name', e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-full mt-1 focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none" />
      </div>

      <div>
        <label className="text-sm font-medium text-gray-700">Max Discount %</label>
        <p className="text-xs text-gray-400">Maximum discount for downgrade offers</p>
        <input type="number" value={form.max_discount_percent || 40} min={0} max={100}
          onChange={e => set('max_discount_percent', parseInt(e.target.value) || 0)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-24 mt-1 focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none" />
      </div>

      <Toggle label="Send to WhatsApp" desc="Deliver agent messages via WhatsApp during chats" field="whatsapp_enabled" />

      <div className="flex items-center gap-3 pt-3 border-t border-gray-100">
        <button onClick={() => onSave(form)} disabled={saving}
          className="flex-1 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white text-sm font-medium rounded-lg transition">
          {saving ? 'Saving...' : 'Save & Continue'}
        </button>
        <button onClick={onSkip}
          className="px-4 py-2.5 text-sm text-gray-500 hover:text-gray-700 transition">
          Use Defaults
        </button>
      </div>
    </div>
  )
}

function App() {
  const [tab, setTab] = useState('overview')
  const [overview, setOverview] = useState(null)
  const [decisions, setDecisions] = useState([])
  const [payments, setPayments] = useState([])
  const [activity, setActivity] = useState([])
  const [config, setConfig] = useState(null)
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [approving, setApproving] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [lastAction, setLastAction] = useState(null)
  const [outcomeFilter, setOutcomeFilter] = useState('')
  const [chatPaymentId, setChatPaymentId] = useState(null)
  const [toasts, setToasts] = useState([])
  const [batchActivity, setBatchActivity] = useState([])
  const [batchProcessing, setBatchProcessing] = useState(false)
  const [dismissingIds, setDismissingIds] = useState({})
  const [sessionStats, setSessionStats] = useState({ resolved: 0, recovered: 0, writtenOff: 0, churned: 0, initialDecisions: null })
  const [showSetup, setShowSetup] = useState(true)
  const prevOverviewRef = useRef({})
  const toastId = useRef(0)

  const addToast = useCallback((message, type = 'info') => {
    const id = ++toastId.current
    setToasts(prev => [...prev, { id, message, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000)
  }, [])

  const dismissToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [ov, dec, pay, act, cfg] = await Promise.all([
        fetch(`${API}/overview`).then(r => r.json()),
        fetch(`${API}/decisions`).then(r => r.json()),
        fetch(`${API}/payments`).then(r => r.json()),
        fetch(`${API}/activity?limit=500`).then(r => r.json()),
        fetch(`${API}/config`).then(r => r.json()),
      ])
      setOverview(prev => {
        if (prev) {
          prevOverviewRef.current = {
            net_recovered: prev.net_recovered || 0,
            recovery_rate: prev.recovery_rate || 0,
            roi: prev.total_cost > 0 ? Math.round(prev.net_recovered / prev.total_cost) : 0,
            total_at_risk: prev.total_at_risk || 0,
          }
        }
        return ov
      })
      setDecisions(dec)
      setPayments(pay)
      setActivity(act)
      setConfig(cfg)
      setError(null)
    } catch {
      setError('Backend offline — run: uvicorn backend.main:app --port 8000')
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const runBatch = async () => {
    setLoading(true); setError(null); setBatchActivity([])
    setBatchProcessing(true)
    try {
      const res = await fetch(`${API}/run-batch`, { method: 'POST' })
      const data = await res.json()
      setLastAction(`${data.auto_executed} auto-executed, ${data.business_decisions} decisions, ${data.gate_blocked} blocked`)
      setSessionStats({ resolved: 0, recovered: 0, writtenOff: 0, churned: 0, initialDecisions: data.business_decisions })
      await refresh()
      const actRes = await fetch(`${API}/activity?limit=30`).then(r => r.json())
      setBatchActivity(actRes || [])
    } catch {
      setError('Failed — is the backend running?')
      addToast('Batch processing failed', 'error')
      setBatchProcessing(false)
    }
    setLoading(false)
  }

  const approveDecision = async (pid, response = 'approve_conversation') => {
    setApproving(true)
    const decisionAmount = decisions.find(d => d.payment_id === pid)?.amount || 0
    try {
      const data = await fetch(`${API}/decisions/${pid}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response }),
      }).then(r => r.json())
      setLastAction(`${pid}: ${data.outcome?.replace(/_/g, ' ')}`)
      addToast(`${pid}: ${data.outcome?.replace(/_/g, ' ')}`, 'success')
      if (response === 'offer_downgrade') {
        setSessionStats(s => ({ ...s, resolved: s.resolved + 1, recovered: s.recovered + decisionAmount }))
      }
      await refresh()
      if (detail?.payment?.payment_id === pid) {
        const d = await fetch(`${API}/payments/${pid}`).then(r => r.json())
        setDetail(d)
      }
    } catch {
      setError('Action failed')
      addToast('Decision action failed', 'error')
    }
    setApproving(false)
  }

  const rejectDecision = async (pid) => {
    setApproving(true)
    const decisionAmount = decisions.find(d => d.payment_id === pid)?.amount || 0
    try {
      await fetch(`${API}/decisions/${pid}/reject`, { method: 'POST' })
      setLastAction(`${pid}: marked churned`)
      addToast(`${pid}: marked churned`, 'warning')
      setSessionStats(s => ({ ...s, resolved: s.resolved + 1, churned: s.churned + 1, writtenOff: s.writtenOff + decisionAmount }))
      setDismissingIds(prev => ({ ...prev, [pid]: 'reject' }))
      await new Promise(r => setTimeout(r, 2500))
      setDismissingIds(prev => { const n = { ...prev }; delete n[pid]; return n })
      await refresh()
      if (detail?.payment?.payment_id === pid) {
        const d = await fetch(`${API}/payments/${pid}`).then(r => r.json())
        setDetail(d)
      }
    } catch {
      setError('Action failed')
      addToast('Reject action failed', 'error')
    }
    setApproving(false)
  }

  const saveConfig = async (form) => {
    setSaving(true)
    try {
      const data = await fetch(`${API}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      }).then(r => r.json())
      setConfig(data)
      setLastAction('Policy saved')
      addToast('Merchant policy saved', 'success')
    } catch {
      setError('Save failed')
      addToast('Failed to save policy', 'error')
    }
    setSaving(false)
  }

  const selectPayment = async (pid) => {
    const d = await fetch(`${API}/payments/${pid}`).then(r => r.json())
    setDetail(d); setTab('detail')
  }

  const navigateToTable = (outcomeFilter) => {
    setOutcomeFilter(outcomeFilter)
    setTab('payments')
  }

  const handleChatComplete = useCallback(async (pid, outcome) => {
    const exitType = (outcome === 'promise_to_pay' || outcome === 'interested_in_downgrade') ? 'success' : 'reject'
    const backendResponse = outcome === 'promise_to_pay' ? 'approve_conversation'
      : outcome === 'interested_in_downgrade' ? 'offer_downgrade'
      : outcome === 'refused' ? 'mark_churned'
      : 'approve_conversation'
    const decisionAmount = decisions.find(d => d.payment_id === pid)?.amount || 0
    try {
      await fetch(`${API}/decisions/${pid}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response: backendResponse }),
      })
    } catch {}
    if (exitType === 'success') {
      setSessionStats(s => ({ ...s, resolved: s.resolved + 1, recovered: s.recovered + decisionAmount }))
    } else {
      setSessionStats(s => ({ ...s, resolved: s.resolved + 1, churned: s.churned + 1, writtenOff: s.writtenOff + decisionAmount }))
    }
    setDismissingIds(prev => ({ ...prev, [pid]: exitType }))
    addToast(`${pid}: ${outcome?.replace(/_/g, ' ')}`, exitType === 'success' ? 'success' : 'warning')
    setTimeout(() => {
      setDismissingIds(prev => { const n = { ...prev }; delete n[pid]; return n })
      refresh()
    }, 2500)
  }, [refresh, addToast, decisions])

  const handleTabSwitch = useCallback((id) => {
    setTab(id)
    setDetail(null)
    if (id !== 'payments') setOutcomeFilter('')
    if (id === 'overview') refresh()
  }, [refresh])

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'decisions', label: 'Decisions', count: decisions.length },
    { id: 'payments', label: 'Payments' },
    { id: 'activity', label: 'Activity' },
    { id: 'test', label: 'Test Entry' },
    { id: 'settings', label: 'Settings' },
  ]

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3.5">
            <img src="/logo.png" alt="Payzen" className="h-14 w-14 object-contain" />
            <div>
              <h1 className="text-xl font-bold text-gray-800">Payzen</h1>
              <p className="text-sm text-gray-400">{config?.brand_name || 'Customer Demo Store'}</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {lastAction && <span className="text-xs text-emerald-600 bg-emerald-50 px-3 py-1 rounded-full max-w-sm truncate">{lastAction}</span>}
            <button onClick={runBatch} disabled={loading}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white text-sm font-medium rounded-lg transition shadow-sm">
              {loading ? 'Processing...' : 'Run Recovery'}
            </button>
          </div>
        </div>
      </header>

      {error && (
        <div className="max-w-7xl mx-auto px-6 mt-4">
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-600">{error}</div>
        </div>
      )}

      <div className="max-w-7xl mx-auto px-6 mt-4">
        <nav className="flex gap-1 border-b border-gray-200 mb-6">
          {tabs.map(t => (
            <button key={t.id} onClick={() => handleTabSwitch(t.id)}
              className={`px-4 py-2.5 text-sm font-medium transition border-b-2 -mb-px flex items-center gap-1.5
                ${tab === t.id || (tab === 'detail' && t.id === 'payments')
                  ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-400 hover:text-gray-600'}`}>
              {t.label}
              {t.count > 0 && (
                <span className="bg-amber-100 text-amber-700 text-xs font-semibold px-1.5 py-0.5 rounded-full">{t.count}</span>
              )}
            </button>
          ))}
        </nav>

        {tab === 'detail' && detail ? (
          <DetailView detail={detail} onBack={() => setTab('payments')} onApprove={approveDecision} onReject={rejectDecision} />
        ) : tab === 'overview' ? (
          <OverviewPage overview={overview} prevOverview={prevOverviewRef.current} onNavigateTable={navigateToTable} onNavigateDecisions={() => setTab('decisions')} recentBatchActivity={batchActivity} recentActivity={activity} sessionStats={sessionStats} onSelectPayment={selectPayment} onNavigateActivity={() => setTab('activity')} />
        ) : tab === 'decisions' ? (
          <DecisionsQueue decisions={decisions} onApprove={approveDecision} onReject={rejectDecision} onSelect={selectPayment} approving={approving} onChat={setChatPaymentId} dismissingIds={dismissingIds} chattingPaymentId={chatPaymentId} />
        ) : tab === 'payments' ? (
          <PaymentsTable payments={payments} onSelect={selectPayment} initialOutcomeFilter={outcomeFilter} />
        ) : tab === 'activity' ? (
          <ActivityFeed activity={activity} onSelectPayment={selectPayment} />
        ) : tab === 'test' ? (
          <TestEntry onResult={() => refresh()} />
        ) : tab === 'settings' ? (
          <SettingsPanel config={config} onSave={saveConfig} saving={saving} />
        ) : null}
      </div>

      <BatchActivityOverlay processing={batchProcessing} items={batchActivity} overview={overview}
        onDismiss={() => { setBatchProcessing(false); setBatchActivity([]); addToast('Recovery batch complete', 'success') }}
        onSelectPayment={selectPayment} />
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <ChatWidget paymentId={chatPaymentId} onClose={() => setChatPaymentId(null)} onChatComplete={handleChatComplete} whatsappEnabled={config?.whatsapp_enabled} />

      {showSetup && config && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] overflow-y-auto mx-4 animate-card-enter">
            <div className="px-6 pt-6 pb-2">
              <h2 className="text-xl font-bold text-gray-800">Welcome to Payzen</h2>
              <p className="text-sm text-gray-400 mt-1">Review your merchant policy before getting started. You can change these anytime in Settings.</p>
            </div>
            <div className="px-6 py-4 grid grid-cols-1 lg:grid-cols-2 gap-6">
              <SetupForm config={config} onSave={(form) => {
                saveConfig(form).then(() => setShowSetup(false))
              }} saving={saving} onSkip={() => setShowSetup(false)} />
              <div className="space-y-4">
                <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 text-sm text-gray-500">
                  <h4 className="font-medium text-gray-700 mb-2">How Tiered Approval Works</h4>
                  <div className="space-y-2">
                    <div className="flex gap-2 items-start">
                      <TierBadge tier={1} />
                      <p><span className="font-medium text-gray-700">Automated</span> — retries, constraint enforcement, timing optimization.</p>
                    </div>
                    <div className="flex gap-2 items-start">
                      <TierBadge tier={2} />
                      <p><span className="font-medium text-gray-700">Policy-driven</span> — SMS, calls, and contact preferences from your settings.</p>
                    </div>
                    <div className="flex gap-2 items-start">
                      <TierBadge tier={3} />
                      <p><span className="font-medium text-gray-700">Business decisions</span> — mandate cancellations need your judgment.</p>
                    </div>
                  </div>
                </div>
                <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-5 text-sm text-gray-600">
                  <h4 className="font-medium text-emerald-800 mb-2">What Gets Recovered</h4>
                  <div className="space-y-1.5">
                    <p><span className="font-medium text-emerald-700">Insufficient funds</span> — auto-retried at optimal times.</p>
                    <p><span className="font-medium text-emerald-700">Bank outages</span> — detected via BIN clustering.</p>
                    <p><span className="font-medium text-emerald-700">AFA stuck</span> — SMS/call nudges for authentication.</p>
                    <p><span className="font-medium text-emerald-700">Card expired</span> — update links sent.</p>
                  </div>
                </div>
                <div className="bg-blue-50 border border-blue-200 rounded-xl p-5 text-sm text-gray-600">
                  <h4 className="font-medium text-blue-800 mb-2">Compliance Built In</h4>
                  <div className="space-y-1.5">
                    <p><span className="font-medium text-blue-700">RBI mandate rules</span> — pre-debit notifications enforced.</p>
                    <p><span className="font-medium text-blue-700">Retry limits</span> — max 3 retries, exponential backoff.</p>
                    <p><span className="font-medium text-blue-700">Audit trail</span> — every action logged for review.</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
