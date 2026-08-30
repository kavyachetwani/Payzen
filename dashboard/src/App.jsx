import { useState, useEffect, useCallback } from 'react'

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
      {data.filter((_, i) => i % Math.max(1, Math.floor(data.length / 6)) === 0).map((d) => {
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

function OverviewPage({ overview, onNavigateTable, onNavigateDecisions }) {
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
    <div className="space-y-8 pb-12">
      {/* Revenue at Risk */}
      <section className="bg-red-50 border border-red-200 rounded-2xl p-6 text-center">
        <p className="text-sm font-medium text-red-400 uppercase tracking-wider mb-1">Revenue at Risk</p>
        <h2 className="text-5xl font-bold text-red-600 mb-2">{fmtFull(o.total_at_risk)}</h2>
        <p className="text-red-400">{o.total_payments} failed payments this cycle</p>
      </section>

      {/* Tier summary */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-5 text-center">
          <p className="text-xs text-emerald-500 uppercase tracking-wider mb-1">Tier 1 & 2 — Auto-executed</p>
          <p className="text-3xl font-bold text-emerald-600">{o.auto_executed || 0}</p>
          <p className="text-xs text-emerald-400 mt-1">retries, SMS, calls — all automated</p>
        </div>
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-5 text-center">
          <p className="text-xs text-blue-500 uppercase tracking-wider mb-1">Non-retryable</p>
          <p className="text-3xl font-bold text-blue-600">{o.outcome_distribution?.card_update_sent || 0} + {o.outcome_distribution?.mandate_resequenced || 0}</p>
          <p className="text-xs text-blue-400 mt-1">card updates + mandate resequences</p>
        </div>
        {hasDecisions ? (
          <button onClick={onNavigateDecisions}
            className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-center hover:shadow-md transition cursor-pointer">
            <p className="text-xs text-amber-500 uppercase tracking-wider mb-1">Tier 3 — Your Decisions</p>
            <p className="text-3xl font-bold text-amber-600">{o.decisions_pending}</p>
            <p className="text-xs text-amber-400 mt-1">{fmtFull(o.decisions_amount)} needing review</p>
          </button>
        ) : (
          <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 text-center">
            <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">Tier 3 — Decisions</p>
            <p className="text-3xl font-bold text-gray-400">0</p>
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

      {/* Recovery Timeline */}
      <section className="bg-white border border-gray-200 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-gray-700 mb-1">Recovery Timeline</h3>
        <p className="text-sm text-gray-400 mb-4">Cumulative net ₹ recovered over simulated time</p>
        <SvgLineChart data={o.timeline || []} baseline={NAIVE_BASELINE} />
      </section>

      {/* Recovery Results */}
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
            return (
              <div key={i} className="flex items-center gap-3">
                <span className="text-sm text-gray-500 w-40 text-right">{d.label}</span>
                <div className="flex-1 h-8 bg-gray-50 rounded-lg overflow-hidden">
                  <div className="h-full rounded-lg flex items-center px-3 transition-all duration-500"
                    style={{ width: `${width}%`, background: d.color }}>
                    <span className="text-white text-sm font-semibold">{d.value}</span>
                  </div>
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
    </div>
  )
}

// ─── DECISIONS (TIER 3) ─────────────────────────────────────

function DecisionsQueue({ decisions, onApprove, onReject, onSelect, approving }) {
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
        {decisions.map(d => (
          <div key={d.payment_id} className="bg-white border border-gray-200 rounded-xl p-5 hover:shadow-sm transition">
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
              <button onClick={() => onApprove(d.payment_id, 'approve_conversation')} disabled={approving}
                className="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 disabled:bg-gray-300 text-white text-sm font-medium rounded-lg transition">
                Start Recovery Conversation
              </button>
              {d.suggested_downgrade && (
                <button onClick={() => onApprove(d.payment_id, 'offer_downgrade')} disabled={approving}
                  className="px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-gray-300 text-white text-sm font-medium rounded-lg transition">
                  Offer ₹{d.suggested_downgrade?.toLocaleString('en-IN')}/mo
                </button>
              )}
              <button onClick={() => onReject(d.payment_id)} disabled={approving}
                className="px-4 py-2 bg-white border border-red-300 hover:bg-red-50 disabled:bg-gray-100 text-red-600 text-sm font-medium rounded-lg transition">
                Mark Churned
              </button>
            </div>
          </div>
        ))}
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
    <div className="max-w-2xl space-y-6 pb-12">
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
        </div>

        <div className="mt-6 flex items-center gap-3">
          <button onClick={() => onSave(form)} disabled={saving || !hasChanges}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white text-sm font-medium rounded-lg transition shadow-sm">
            {saving ? 'Saving...' : 'Save Policy'}
          </button>
          {!hasChanges && <span className="text-xs text-gray-400">No unsaved changes</span>}
        </div>
      </div>

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
    </div>
  )
}

// ─── ACTIVITY FEED ──────────────────────────────────────────

function ActivityFeed({ activity }) {
  if (!activity || activity.length === 0) {
    return (
      <div className="text-center py-32">
        <div className="text-6xl mb-4">📋</div>
        <h2 className="text-xl font-semibold text-gray-700 mb-2">No activity yet</h2>
        <p className="text-gray-400">Run a batch to see the activity feed</p>
      </div>
    )
  }

  return (
    <div className="space-y-2 pb-12">
      <p className="text-sm text-gray-400 mb-4">Recent pipeline activity — newest first</p>
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-left text-gray-500 border-b border-gray-200">
              <th className="px-4 py-3 font-medium">Payment</th>
              <th className="px-4 py-3 font-medium">Action</th>
              <th className="px-4 py-3 font-medium">Outcome</th>
              <th className="px-4 py-3 font-medium">Amount</th>
              <th className="px-4 py-3 font-medium">Recovered</th>
              <th className="px-4 py-3 font-medium">Cause</th>
              <th className="px-4 py-3 font-medium">Time</th>
            </tr>
          </thead>
          <tbody>
            {activity.slice(0, 100).map((a, i) => (
              <tr key={i} className="border-b border-gray-100 hover:bg-blue-50/30 transition">
                <td className="px-4 py-2.5 font-mono text-xs text-gray-700">{a.payment_id}</td>
                <td className="px-4 py-2.5">
                  <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium
                    ${a.action === 'auto_retry' ? 'bg-emerald-100 text-emerald-700' :
                      a.action?.startsWith('sms') ? 'bg-blue-100 text-blue-700' :
                      a.action?.startsWith('call') ? 'bg-purple-100 text-purple-700' :
                      a.action?.startsWith('decision:') ? 'bg-amber-100 text-amber-700' :
                      'bg-gray-100 text-gray-700'}`}>
                    {a.action?.replace(/_/g, ' ')}
                  </span>
                </td>
                <td className="px-4 py-2.5"><OutcomeBadge outcome={a.outcome} /></td>
                <td className="px-4 py-2.5 font-mono text-gray-700">{fmtFull(a.amount)}</td>
                <td className="px-4 py-2.5 font-mono">
                  {a.amount_recovered > 0
                    ? <span className="text-emerald-600">+{fmtFull(a.amount_recovered)}</span>
                    : <span className="text-gray-400">₹0</span>}
                </td>
                <td className="px-4 py-2.5 text-xs text-gray-500">{a.cause?.replace(/_/g, ' ')}</td>
                <td className="px-4 py-2.5 text-xs text-gray-400 font-mono">{a.sim_timestamp?.slice(0, 16)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {activity.length > 100 && (
          <p className="text-xs text-gray-400 text-center py-2 border-t border-gray-100">Showing first 100 of {activity.length}</p>
        )}
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
          <div><span className="text-gray-400">Ground Truth:</span> <span className="text-gray-700">{payment.ground_truth_cause?.replace(/_/g, ' ')}</span></div>
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

  const refresh = useCallback(async () => {
    try {
      const [ov, dec, pay, act, cfg] = await Promise.all([
        fetch(`${API}/overview`).then(r => r.json()),
        fetch(`${API}/decisions`).then(r => r.json()),
        fetch(`${API}/payments`).then(r => r.json()),
        fetch(`${API}/activity`).then(r => r.json()),
        fetch(`${API}/config`).then(r => r.json()),
      ])
      setOverview(ov)
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
    setLoading(true); setError(null)
    try {
      const res = await fetch(`${API}/run-batch`, { method: 'POST' })
      const data = await res.json()
      setLastAction(`${data.auto_executed} auto-executed, ${data.business_decisions} decisions, ${data.gate_blocked} blocked`)
      await refresh()
    } catch { setError('Failed — is the backend running?') }
    setLoading(false)
  }

  const approveDecision = async (pid, response = 'approve_conversation') => {
    setApproving(true)
    try {
      const data = await fetch(`${API}/decisions/${pid}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response }),
      }).then(r => r.json())
      setLastAction(`${pid}: ${data.outcome?.replace(/_/g, ' ')}`)
      await refresh()
      if (detail?.payment?.payment_id === pid) {
        const d = await fetch(`${API}/payments/${pid}`).then(r => r.json())
        setDetail(d)
      }
    } catch { setError('Action failed') }
    setApproving(false)
  }

  const rejectDecision = async (pid) => {
    setApproving(true)
    try {
      await fetch(`${API}/decisions/${pid}/reject`, { method: 'POST' })
      setLastAction(`${pid}: marked churned`)
      await refresh()
      if (detail?.payment?.payment_id === pid) {
        const d = await fetch(`${API}/payments/${pid}`).then(r => r.json())
        setDetail(d)
      }
    } catch { setError('Action failed') }
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
    } catch { setError('Save failed') }
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

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'decisions', label: 'Decisions', count: decisions.length },
    { id: 'payments', label: 'Payments' },
    { id: 'activity', label: 'Activity' },
    { id: 'settings', label: 'Settings' },
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
              <h1 className="text-base font-semibold text-gray-800">{config?.brand_name || 'Demo Store'}</h1>
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
          <DetailView detail={detail} onBack={() => setTab('payments')} onApprove={approveDecision} onReject={rejectDecision} />
        ) : tab === 'overview' ? (
          <OverviewPage overview={overview} onNavigateTable={navigateToTable} onNavigateDecisions={() => setTab('decisions')} />
        ) : tab === 'decisions' ? (
          <DecisionsQueue decisions={decisions} onApprove={approveDecision} onReject={rejectDecision} onSelect={selectPayment} approving={approving} />
        ) : tab === 'payments' ? (
          <PaymentsTable payments={payments} onSelect={selectPayment} initialOutcomeFilter={outcomeFilter} />
        ) : tab === 'activity' ? (
          <ActivityFeed activity={activity} />
        ) : tab === 'settings' ? (
          <SettingsPanel config={config} onSave={saveConfig} saving={saving} />
        ) : null}
      </div>
    </div>
  )
}

export default App
