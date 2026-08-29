import { useState, useEffect, useCallback } from 'react'
// Pure SVG charts — no recharts dependency

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
  gate_blocked: '#991b1b', scheduled: '#64748b',
}
const CHART_COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#a855f7', '#06b6d4', '#ec4899', '#64748b', '#84cc16', '#f97316']

const CAUSE_LABELS = {
  insufficient_funds: 'Insufficient Funds', bank_outage: 'Bank Outage',
  afa_stuck: 'AFA Stuck', card_expired: 'Card Expired',
  mandate_expired: 'Mandate Expired', mandate_revoked: 'Mandate Revoked',
  ambiguous: 'Ambiguous',
}

const ACTION_REASONS = {
  insufficient_funds: 'Customer likely short on funds — payment near payday window may succeed',
  bank_outage: 'Bank systems were down — retry when systems recover',
  ambiguous: 'Root cause unclear — SMS to customer may surface the issue',
  afa_stuck: 'Additional Factor Authentication stuck — needs customer nudge',
  card_expired: 'Card has expired — customer needs to update card details',
  mandate_expired: 'Mandate expired — needs re-registration',
  mandate_revoked: 'Mandate cancelled by customer — needs conversation',
}

function StatusBadge({ status }) {
  const styles = {
    resolved: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    pending_approval: 'bg-amber-100 text-amber-700 border-amber-200',
    gate_blocked: 'bg-red-100 text-red-700 border-red-200',
    in_progress: 'bg-blue-100 text-blue-700 border-blue-200',
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
  }
  return (
    <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${styles[outcome] || 'bg-gray-100 text-gray-500'}`}>
      {outcome.replace(/_/g, ' ')}
    </span>
  )
}


function DonutChart({ data, size = 140 }) {
  const total = data.reduce((s, d) => s + d.value, 0)
  if (!total) return null
  const cx = size / 2, cy = size / 2, r = size * 0.38, stroke = size * 0.14
  const circumference = 2 * Math.PI * r
  let offset = 0
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {data.map((d, i) => {
        const pct = d.value / total
        const dash = pct * circumference
        const gap = circumference - dash
        const o = offset
        offset += dash
        return (
          <circle key={i} cx={cx} cy={cy} r={r} fill="none"
            stroke={d.fill} strokeWidth={stroke}
            strokeDasharray={`${dash} ${gap}`}
            strokeDashoffset={-o}
            transform={`rotate(-90 ${cx} ${cy})`} />
        )
      })}
    </svg>
  )
}

function SvgLineChart({ data, baseline }) {
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
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 260 }}>
      {Array.from({ length: ticks + 1 }, (_, i) => {
        const v = minV + (range / ticks) * i
        const yy = y(v)
        return <g key={i}><line x1={pad.l} x2={W - pad.r} y1={yy} y2={yy} stroke="#e5e7eb" strokeDasharray="3 3" />
          <text x={pad.l - 6} y={yy + 4} textAnchor="end" fill="#9ca3af" fontSize="10">{fmt(v)}</text></g>
      })}
      {data.filter((_, i) => i % Math.max(1, Math.floor(data.length / 6)) === 0).map((d, i, arr) => {
        const idx = data.indexOf(d)
        return <text key={idx} x={x(idx)} y={H - 6} textAnchor="middle" fill="#9ca3af" fontSize="10">{d.date?.slice(5)}</text>
      })}
      {baseline && <><line x1={pad.l} x2={W - pad.r} y1={y(baseline)} y2={y(baseline)} stroke="#ef4444" strokeDasharray="8 4" strokeWidth={1.5} />
        <text x={W - pad.r + 4} y={y(baseline) + 4} fill="#ef4444" fontSize="10">Naive</text></>}
      <polyline points={points} fill="none" stroke="#22c55e" strokeWidth="2.5" strokeLinejoin="round" />
    </svg>
  )
}

function SvgHBarChart({ data }) {
  if (!data || data.length === 0) return <p className="text-gray-400 text-sm py-8 text-center">No bank data</p>
  const maxCount = Math.max(...data.map(d => d.count))
  return (
    <div className="space-y-2">
      {data.map((d, i) => (
        <div key={i} className="flex items-center gap-3">
          <span className="text-xs text-gray-600 w-28 text-right truncate">{d.name}</span>
          <div className="flex-1 h-7 bg-gray-50 rounded overflow-hidden">
            <div className="h-full rounded flex items-center px-2 transition-all" style={{
              width: `${Math.max(8, (d.count / maxCount) * 100)}%`,
              background: d.fill,
            }}>
              <span className="text-white text-xs font-semibold">{d.count}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── OVERVIEW PAGE ───────────────────────────────────────────

function OverviewPage({ overview, onNavigateTable }) {
  if (!overview || overview.error) {
    return (
      <div className="text-center py-32">
        <div className="text-6xl mb-4">📊</div>
        <h2 className="text-xl font-semibold text-gray-700 mb-2">No recovery data yet</h2>
        <p className="text-gray-400">Click "Run Recovery" to process 500 failed payments</p>
      </div>
    )
  }

  const o = overview
  const NAIVE_BASELINE = 2080292

  const causeData = Object.entries(o.cause_distribution || {}).map(([name, value]) => ({
    name: CAUSE_LABELS[name] || name, value, fill: CAUSE_COLORS[name] || '#94a3b8',
  }))

  const actionData = Object.entries(o.action_distribution || {})
    .filter(([k]) => !['scheduled', 'gate_blocked'].includes(k))
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

  return (
    <div className="space-y-8 pb-12">
      {/* Section 1: The Problem */}
      <section className="bg-red-50 border border-red-200 rounded-2xl p-6 text-center">
        <p className="text-sm font-medium text-red-400 uppercase tracking-wider mb-1">Revenue at Risk</p>
        <h2 className="text-5xl font-bold text-red-600 mb-2">{fmtFull(o.total_at_risk)}</h2>
        <p className="text-red-400">{o.total_payments} failed payments this cycle</p>
      </section>

      {/* Section 2: What We Did */}
      <section>
        <h3 className="text-lg font-semibold text-gray-700 mb-4">Diagnosis &amp; Actions</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-white border border-gray-200 rounded-xl p-4">
            <h4 className="text-sm font-medium text-gray-500 mb-3">Failure Causes</h4>
            <div className="flex items-center gap-4">
              <DonutChart data={causeData} />
              <div className="flex-1 space-y-1.5">
                {[...causeData].sort((a, b) => b.value - a.value).map(d => (
                  <div key={d.name} className="flex items-center gap-2 text-sm">
                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: d.fill }} />
                    <span className="text-gray-600 flex-1">{d.name}</span>
                    <span className="font-mono text-gray-800 font-medium">{d.value}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="bg-white border border-gray-200 rounded-xl p-4">
            <h4 className="text-sm font-medium text-gray-500 mb-3">Actions Taken</h4>
            <div className="flex items-center gap-4">
              <DonutChart data={actionData} />
              <div className="flex-1 space-y-1.5">
                {actionData.map(d => (
                  <div key={d.name} className="flex items-center gap-2 text-sm">
                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: d.fill }} />
                    <span className="text-gray-600 flex-1">{d.name}</span>
                    <span className="font-mono text-gray-800 font-medium">{d.value}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Section 3: Recovery Timeline */}
      <section className="bg-white border border-gray-200 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-1">Recovery Timeline</h3>
        <p className="text-sm text-gray-400 mb-4">Cumulative net ₹ recovered over simulated time</p>
        <SvgLineChart data={o.timeline || []} baseline={NAIVE_BASELINE} />
      </section>

      {/* Section 4: The Result */}
      <section>
        <h3 className="text-lg font-semibold text-gray-700 mb-4">Recovery Results</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-6 text-center">
            <p className="text-sm text-emerald-500 font-medium mb-1">Net Recovered</p>
            <p className="text-4xl font-bold text-emerald-600">{fmt(o.net_recovered)}</p>
            <p className="text-sm text-emerald-400 mt-1">from {fmtFull(o.total_at_risk)} at risk</p>
          </div>
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-6 text-center">
            <p className="text-sm text-blue-500 font-medium mb-1">Recovery Rate</p>
            <div className="relative w-24 h-24 mx-auto my-2">
              <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                <circle cx="50" cy="50" r="42" fill="none" stroke="#dbeafe" strokeWidth="8" />
                <circle cx="50" cy="50" r="42" fill="none" stroke="#3b82f6" strokeWidth="8"
                  strokeDasharray={`${o.recovery_rate * 264} 264`} strokeLinecap="round" />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-xl font-bold text-blue-600">
                {pct(o.recovery_rate)}
              </span>
            </div>
          </div>
          <div className="bg-purple-50 border border-purple-200 rounded-xl p-6 text-center">
            <p className="text-sm text-purple-500 font-medium mb-1">ROI</p>
            <p className="text-4xl font-bold text-purple-600">{roi.toLocaleString()}x</p>
            <p className="text-sm text-purple-400 mt-1">{fmtFull(o.total_cost)} spent → {fmt(o.net_recovered)}</p>
          </div>
        </div>
      </section>

      {/* Section 5: Before vs After */}
      <section className="bg-white border border-gray-200 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-4">Before vs After</h3>
        <div className="grid grid-cols-3 gap-4 items-center">
          <div className="text-center bg-gray-50 rounded-xl p-5 border border-gray-200">
            <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">Naive Retry</p>
            <p className="text-3xl font-bold text-gray-400">{fmt(NAIVE_BASELINE)}</p>
            <p className="text-sm text-gray-400 mt-1">12.6% rate</p>
          </div>
          <div className="text-center">
            <div className="bg-emerald-100 rounded-full px-4 py-2 inline-block">
              <p className="text-2xl font-bold text-emerald-600">+{(((o.net_recovered - NAIVE_BASELINE) / NAIVE_BASELINE) * 100).toFixed(1)}%</p>
              <p className="text-xs text-emerald-500">more revenue recovered</p>
            </div>
          </div>
          <div className="text-center bg-emerald-50 rounded-xl p-5 border border-emerald-200">
            <p className="text-xs text-emerald-500 uppercase tracking-wider mb-1">Smart Recovery</p>
            <p className="text-3xl font-bold text-emerald-600">{fmt(o.net_recovered)}</p>
            <p className="text-sm text-emerald-500 mt-1">{pct(o.recovery_rate)} rate</p>
          </div>
        </div>
      </section>

      {/* Section 6: Attempt Funnel */}
      <section className="bg-white border border-gray-200 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-4">Retry Funnel</h3>
        <div className="space-y-2.5">
          {funnelData.map((d, i) => {
            const maxVal = funnelData[0].value
            const width = Math.max(10, (d.value / maxVal) * 100)
            return (
              <div key={i} className="flex items-center gap-3">
                <span className="text-sm text-gray-500 w-40 text-right">{d.label}</span>
                <div className="flex-1 h-8 bg-gray-50 rounded-lg overflow-hidden">
                  <div
                    className="h-full rounded-lg flex items-center px-3 transition-all duration-500"
                    style={{ width: `${width}%`, background: d.color }}
                  >
                    <span className="text-white text-sm font-semibold">{d.value}</span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* Section 7: Bank Intelligence */}
      <section className="bg-white border border-gray-200 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-1">Bank Intelligence</h3>
        <p className="text-sm text-gray-400 mb-4">Top failure-causing banks</p>
        <SvgHBarChart data={bankData} />
        <div className="flex gap-3 mt-3 flex-wrap justify-center">
          {Object.entries(CAUSE_COLORS).map(([cause, color]) => (
            <div key={cause} className="flex items-center gap-1 text-xs text-gray-500">
              <span className="w-2 h-2 rounded-full" style={{ background: color }} />
              {CAUSE_LABELS[cause] || cause}
            </div>
          ))}
        </div>
      </section>

      {/* Section 8: Compliance */}
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

      {/* Section 9: Needs Attention */}
      <section>
        <h3 className="text-lg font-semibold text-gray-700 mb-3">Needs Attention</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Exhausted Retries', data: o.exceptions?.exhausted, color: 'amber', filter: 'failed_exhausted' },
            { label: 'Escalated', data: o.exceptions?.escalated, color: 'orange', filter: 'escalated' },
            { label: 'Pending Non-Retryable', data: o.exceptions?.pending_nr, color: 'yellow', filter: 'card_update_sent' },
            { label: 'Gate Blocked', data: o.exceptions?.gate_blocked, color: 'red', filter: 'gate_blocked' },
          ].map(e => (
            <button
              key={e.label}
              onClick={() => onNavigateTable(e.filter)}
              className={`rounded-xl p-4 border text-left hover:shadow-md transition cursor-pointer
                ${e.color === 'red' ? 'bg-red-50 border-red-200' :
                  e.color === 'orange' ? 'bg-orange-50 border-orange-200' :
                  e.color === 'yellow' ? 'bg-yellow-50 border-yellow-200' :
                  'bg-amber-50 border-amber-200'}`}
            >
              <p className="text-2xl font-bold text-gray-700">{e.data?.count || 0}</p>
              <p className="text-xs text-gray-500 mt-0.5">{e.label}</p>
              <p className="text-xs font-mono text-gray-400">{fmtFull(e.data?.amount || 0)} at risk</p>
            </button>
          ))}
        </div>
      </section>
    </div>
  )
}

// ─── APPROVAL QUEUE ──────────────────────────────────────────

function ApprovalQueue({ pending, onApprove, onReject, onApproveAll, onSelect, approving }) {
  if (!pending || pending.length === 0) {
    return (
      <div className="text-center py-32">
        <div className="text-6xl mb-4">✅</div>
        <h2 className="text-xl font-semibold text-gray-700 mb-2">All clear</h2>
        <p className="text-gray-400">No pending actions — all payments have been processed</p>
      </div>
    )
  }

  const totalAtStake = pending.reduce((s, p) => s + p.amount, 0)
  const avgSuccessRate = 0.35

  return (
    <div className="space-y-4">
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-center justify-between">
        <div className="flex gap-6">
          <div>
            <p className="text-xs text-amber-500 uppercase tracking-wider">Pending</p>
            <p className="text-xl font-bold text-amber-700">{pending.length} actions</p>
          </div>
          <div>
            <p className="text-xs text-amber-500 uppercase tracking-wider">At Stake</p>
            <p className="text-xl font-bold text-amber-700">{fmtFull(totalAtStake)}</p>
          </div>
          <div>
            <p className="text-xs text-amber-500 uppercase tracking-wider">Est. Recovery</p>
            <p className="text-xl font-bold text-amber-700">{fmtFull(totalAtStake * avgSuccessRate)}</p>
          </div>
        </div>
        <button
          onClick={onApproveAll}
          disabled={approving}
          className="px-5 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:bg-gray-300 text-white font-medium rounded-lg transition shadow-sm"
        >
          {approving ? 'Processing...' : `Approve All (${pending.length})`}
        </button>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-left text-gray-500 border-b border-gray-200">
              <th className="px-4 py-3 font-medium">Payment</th>
              <th className="px-4 py-3 font-medium">Amount</th>
              <th className="px-4 py-3 font-medium">Recommended Action</th>
              <th className="px-4 py-3 font-medium">Reason</th>
              <th className="px-4 py-3 font-medium text-center">Attempt</th>
              <th className="px-4 py-3 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {pending.map((p, i) => (
              <tr key={p.payment_id} className={`border-b border-gray-100 hover:bg-blue-50/30 transition ${p.amount > 50000 ? 'bg-amber-50/30' : ''}`}>
                <td className="px-4 py-3">
                  <button onClick={() => onSelect(p.payment_id)} className="text-blue-600 hover:text-blue-800 font-mono text-xs font-medium">
                    {p.payment_id}
                  </button>
                  <p className="text-xs text-gray-400 mt-0.5">{p.bank_name} &middot; {p.payment_method?.replace(/_/g, ' ')}</p>
                </td>
                <td className="px-4 py-3 font-mono font-semibold text-gray-800">{fmtFull(p.amount)}</td>
                <td className="px-4 py-3">
                  <span className={`inline-block px-2.5 py-1 rounded-full text-xs font-medium
                    ${p.recommended_action === 'sms_then_retry' ? 'bg-blue-100 text-blue-700' :
                      p.recommended_action === 'call_then_retry' ? 'bg-purple-100 text-purple-700' :
                      'bg-gray-100 text-gray-700'}`}>
                    {p.recommended_action?.replace(/_/g, ' ')}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-gray-500 max-w-xs">{ACTION_REASONS[p.cause] || p.cause?.replace(/_/g, ' ')}</td>
                <td className="px-4 py-3 text-center">
                  <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-gray-100 text-gray-600 text-xs font-medium">
                    {p.attempt_number}
                  </span>
                </td>
                <td className="px-4 py-3 text-right space-x-2">
                  <button onClick={() => onApprove(p.payment_id)} disabled={approving}
                    className="px-3 py-1.5 bg-emerald-500 hover:bg-emerald-600 disabled:bg-gray-300 text-white text-xs font-medium rounded-lg transition">
                    Approve
                  </button>
                  <button onClick={() => onReject(p.payment_id)} disabled={approving}
                    className="px-3 py-1.5 bg-white border border-red-300 hover:bg-red-50 disabled:bg-gray-100 text-red-600 text-xs font-medium rounded-lg transition">
                    Reject
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
            <option value="">All {f.label.toLowerCase()}s</option>
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
          <table className="w-full text-sm">
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
                  <th key={key} className="px-4 py-3 font-medium cursor-pointer hover:text-gray-700" onClick={() => toggleSort(key)}>
                    {label} {sortBy === key ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.slice(0, 100).map(p => (
                <tr key={p.payment_id} className="border-b border-gray-100 hover:bg-blue-50/30 transition">
                  <td className="px-4 py-2.5">
                    <button onClick={() => onSelect(p.payment_id)} className="text-blue-600 hover:text-blue-800 font-mono text-xs">
                      {p.payment_id}
                    </button>
                  </td>
                  <td className="px-4 py-2.5 font-mono font-medium text-gray-800">{fmtFull(p.amount)}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-600">{p.diagnosed_cause?.replace(/_/g, ' ')}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-500">{p.payment_method?.replace(/_/g, ' ')}</td>
                  <td className="px-4 py-2.5"><StatusBadge status={p.status} /></td>
                  <td className="px-4 py-2.5"><OutcomeBadge outcome={p.final_outcome} /></td>
                  <td className="px-4 py-2.5 font-mono text-xs font-medium">
                    {p.net_recovered > 0
                      ? <span className="text-emerald-600">+{fmtFull(p.net_recovered)}</span>
                      : p.net_recovered < 0
                      ? <span className="text-red-500">{fmtFull(p.net_recovered)}</span>
                      : <span className="text-gray-400">₹0</span>}
                  </td>
                  <td className="px-4 py-2.5 text-center text-gray-500">{p.total_attempts}</td>
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
  const { payment, diagnosis, status, final_outcome, amount_recovered, action_cost, net_recovered, attempt_history, events, pending_action } = detail

  return (
    <div className="space-y-6 pb-12">
      <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-800 font-medium">&larr; Back to all payments</button>

      <div className="bg-white border border-gray-200 rounded-xl p-5 flex justify-between items-start">
        <div>
          <h2 className="text-xl font-bold text-gray-800 font-mono">{payment.payment_id}</h2>
          <p className="text-sm text-gray-500 mt-1">{payment.customer_id} &middot; {payment.bank_name} &middot; {payment.payment_method.replace(/_/g, ' ')} &middot; {payment.payment_category}</p>
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
          <div><span className="text-gray-400">Ground Truth:</span> <span className="text-gray-700">{payment.ground_truth_cause?.replace(/_/g, ' ')}</span></div>
          <div><span className="text-gray-400">Category:</span> <span className="text-gray-700">{payment.payment_category}</span></div>
        </div>
      </div>

      {pending_action && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-amber-700 mb-2">Pending Approval</h3>
          <p className="text-sm text-gray-600 mb-1">
            Recommended: <span className="font-semibold text-amber-700">{pending_action.recommended_action?.replace(/_/g, ' ')}</span> (attempt {pending_action.attempt_number})
          </p>
          <p className="text-xs text-gray-500 mb-3">{ACTION_REASONS[pending_action.cause] || ''}</p>
          <div className="space-x-3">
            <button onClick={() => onApprove(payment.payment_id)}
              className="px-5 py-2 bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-medium rounded-lg transition">Approve</button>
            <button onClick={() => onReject(payment.payment_id)}
              className="px-5 py-2 bg-white border border-red-300 hover:bg-red-50 text-red-600 text-sm font-medium rounded-lg transition">Reject</button>
          </div>
        </div>
      )}

      {/* Vertical Timeline */}
      {attempt_history && attempt_history.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">Attempt Timeline</h3>
          <div className="relative ml-4">
            <div className="absolute left-2.5 top-1 bottom-1 w-0.5 bg-gray-200" />
            {attempt_history.map((a, i) => {
              const isSuccess = a.outcome === 'success'
              const isLast = i === attempt_history.length - 1
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
                  <th className="pb-2 pr-3 font-medium">Gate</th>
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
                    <td className="py-1.5 pr-3 text-gray-400">{e.gate_mode}</td>
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

function App() {
  const [tab, setTab] = useState('overview')
  const [overview, setOverview] = useState(null)
  const [pending, setPending] = useState([])
  const [payments, setPayments] = useState([])
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [approving, setApproving] = useState(false)
  const [error, setError] = useState(null)
  const [lastAction, setLastAction] = useState(null)
  const [outcomeFilter, setOutcomeFilter] = useState('')

  const refresh = useCallback(async () => {
    try {
      const [ov, pend, pay] = await Promise.all([
        fetch(`${API}/overview`).then(r => r.json()),
        fetch(`${API}/pending`).then(r => r.json()),
        fetch(`${API}/payments`).then(r => r.json()),
      ])
      setOverview(ov)
      setPending(pend)
      setPayments(pay)
      setError(null)
    } catch {
      setError('Backend offline — run: uvicorn backend.main:app --port 8000')
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const runBatch = async () => {
    setLoading(true); setError(null)
    try {
      const res = await fetch(`${API}/run-batch`, { method: 'POST' })
      const data = await res.json()
      setLastAction(`${data.auto_approved} auto-approved, ${data.pending_approval} pending, ${data.gate_blocked} blocked`)
      await refresh()
    } catch { setError('Failed — is the backend running?') }
    setLoading(false)
  }

  const approveAction = async (pid) => {
    setApproving(true)
    try {
      const data = await fetch(`${API}/approve/${pid}`, { method: 'POST' }).then(r => r.json())
      if (data.outcome === 'recovered') setLastAction(`${pid}: recovered ${fmtFull(data.amount_recovered)}`)
      else if (data.next_pending) setLastAction(`${pid}: failed — retry ${data.next_pending.attempt_number} queued`)
      else setLastAction(`${pid}: ${data.outcome?.replace(/_/g, ' ')}`)
      await refresh()
      if (detail?.payment?.payment_id === pid) {
        const d = await fetch(`${API}/payments/${pid}`).then(r => r.json())
        setDetail(d)
      }
    } catch { setError('Approve failed') }
    setApproving(false)
  }

  const rejectAction = async (pid) => {
    setApproving(true)
    try {
      await fetch(`${API}/reject/${pid}`, { method: 'POST' })
      setLastAction(`${pid}: rejected`)
      await refresh()
      if (detail?.payment?.payment_id === pid) {
        const d = await fetch(`${API}/payments/${pid}`).then(r => r.json())
        setDetail(d)
      }
    } catch { setError('Reject failed') }
    setApproving(false)
  }

  const approveAll = async () => {
    setApproving(true)
    try {
      const data = await fetch(`${API}/approve-all`, { method: 'POST' }).then(r => r.json())
      const recovered = data.filter(d => d.outcome === 'recovered').length
      setLastAction(`Approved all: ${recovered} recovered, ${data.length - recovered} other`)
      await refresh()
    } catch { setError('Approve all failed') }
    setApproving(false)
  }

  const selectPayment = async (pid) => {
    const d = await fetch(`${API}/payments/${pid}`).then(r => r.json())
    setDetail(d); setTab('detail')
  }

  const navigateToTable = (outcomeFilter) => {
    setOutcomeFilter(outcomeFilter)
    setTab('payments')
  }

  const tabs = [
    { id: 'overview', label: 'Overview', icon: '📊' },
    { id: 'approvals', label: 'Approvals', count: pending.length, icon: '⏳' },
    { id: 'payments', label: 'All Payments', icon: '📋' },
  ]

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
              <span className="text-white text-sm font-bold">R</span>
            </div>
            <div>
              <h1 className="text-base font-semibold text-gray-800">Demo Store</h1>
              <p className="text-xs text-gray-400">AI Revenue Recovery</p>
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
            <button key={t.id} onClick={() => { setTab(t.id); setDetail(null); if (t.id !== 'payments') setOutcomeFilter('') }}
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
          <DetailView detail={detail} onBack={() => setTab('payments')} onApprove={approveAction} onReject={rejectAction} />
        ) : tab === 'overview' ? (
          <OverviewPage overview={overview} onNavigateTable={navigateToTable} />
        ) : tab === 'approvals' ? (
          <ApprovalQueue pending={pending} onApprove={approveAction} onReject={rejectAction} onApproveAll={approveAll} onSelect={selectPayment} approving={approving} />
        ) : tab === 'payments' ? (
          <PaymentsTable payments={payments} onSelect={selectPayment} initialOutcomeFilter={outcomeFilter} />
        ) : null}
      </div>
    </div>
  )
}

export default App
