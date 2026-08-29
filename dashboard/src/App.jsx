import { useState, useEffect, useCallback } from 'react'

const API = '/api'

function formatINR(n) {
  if (n == null) return '₹0'
  return '₹' + Number(n).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function pct(n) {
  if (n == null) return '0%'
  return (n * 100).toFixed(1) + '%'
}

function StatusBadge({ status }) {
  const colors = {
    resolved: 'bg-emerald-900/50 text-emerald-300 border-emerald-700',
    pending_approval: 'bg-amber-900/50 text-amber-300 border-amber-700',
    gate_blocked: 'bg-red-900/50 text-red-300 border-red-700',
    in_progress: 'bg-blue-900/50 text-blue-300 border-blue-700',
    unprocessed: 'bg-slate-800 text-slate-400 border-slate-600',
  }
  return (
    <span className={`px-2 py-0.5 text-xs rounded border ${colors[status] || colors.unprocessed}`}>
      {status?.replace(/_/g, ' ')}
    </span>
  )
}

function OutcomeBadge({ outcome }) {
  if (!outcome) return null
  const colors = {
    recovered: 'text-emerald-400',
    failed_exhausted: 'text-red-400',
    gate_blocked: 'text-red-400',
    escalated: 'text-orange-400',
    card_update_sent: 'text-blue-400',
    mandate_resequenced: 'text-blue-400',
    merchant_rejected: 'text-red-400',
  }
  return <span className={`text-xs ${colors[outcome] || 'text-slate-400'}`}>{outcome.replace(/_/g, ' ')}</span>
}

function MetricCard({ label, value, sub }) {
  return (
    <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wider mb-1">{label}</div>
      <div className="text-2xl font-semibold text-white">{value}</div>
      {sub && <div className="text-xs text-slate-400 mt-1">{sub}</div>}
    </div>
  )
}

function OverviewTab({ overview, onRefresh }) {
  if (!overview || overview.error) {
    return (
      <div className="text-center py-20 text-slate-400">
        <p className="text-lg mb-2">No batch data yet</p>
        <p className="text-sm">Click "Run Batch" to process 500 payment failures</p>
      </div>
    )
  }

  const o = overview
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MetricCard label="Total at Risk" value={formatINR(o.total_at_risk)} sub={`${o.total_payments} payments`} />
        <MetricCard label="Net Recovered" value={formatINR(o.net_recovered)} sub={pct(o.recovery_rate) + ' rate'} />
        <MetricCard label="Action Costs" value={formatINR(o.total_cost)} />
        <MetricCard label="Resolved" value={o.resolved_count} sub={`of ${o.total_payments}`} />
        <MetricCard label="Pending" value={o.pending_count} sub="awaiting approval" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-slate-300 mb-3">Action Distribution</h3>
          <div className="space-y-2">
            {Object.entries(o.action_distribution || {})
              .sort((a, b) => b[1] - a[1])
              .map(([action, count]) => (
                <div key={action} className="flex justify-between text-sm">
                  <span className="text-slate-400">{action.replace(/_/g, ' ')}</span>
                  <span className="text-white font-mono">{count}</span>
                </div>
              ))}
          </div>
        </div>

        <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-slate-300 mb-3">Outcome Distribution</h3>
          <div className="space-y-2">
            {Object.entries(o.outcome_distribution || {})
              .sort((a, b) => b[1] - a[1])
              .map(([outcome, count]) => (
                <div key={outcome} className="flex justify-between text-sm">
                  <span className="text-slate-400">{outcome.replace(/_/g, ' ')}</span>
                  <span className="text-white font-mono">{count}</span>
                </div>
              ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-slate-300 mb-3">Attempt Distribution (Retryable)</h3>
          <div className="space-y-2">
            {Object.entries(o.attempt_distribution || {})
              .sort((a, b) => a[0].localeCompare(b[0]))
              .map(([key, count]) => (
                <div key={key} className="flex justify-between text-sm">
                  <span className="text-slate-400">{key.replace(/_/g, ' ')}</span>
                  <span className="text-white font-mono">{count}</span>
                </div>
              ))}
          </div>
        </div>

        <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-slate-300 mb-3">Compliance</h3>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">DND gate blocks</span>
              <span className="text-white font-mono">{o.compliance?.dnd_blocks || 0}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">Total events logged</span>
              <span className="text-white font-mono">{o.events_logged || 0}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">Summaries logged</span>
              <span className="text-white font-mono">{o.summaries_logged || 0}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function ApprovalQueue({ pending, onApprove, onReject, onApproveAll, onSelect, approving }) {
  if (!pending || pending.length === 0) {
    return (
      <div className="text-center py-20 text-slate-400">
        <p className="text-lg">No pending actions</p>
        <p className="text-sm mt-1">All actions have been processed</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <span className="text-sm text-slate-400">{pending.length} actions awaiting approval</span>
        <button
          onClick={onApproveAll}
          disabled={approving}
          className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-600 text-white text-sm rounded transition"
        >
          {approving ? 'Processing...' : `Approve All (${pending.length})`}
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-400 border-b border-slate-700">
              <th className="pb-2 pr-3">Payment ID</th>
              <th className="pb-2 pr-3">Amount</th>
              <th className="pb-2 pr-3">Cause</th>
              <th className="pb-2 pr-3">Action</th>
              <th className="pb-2 pr-3">Attempt</th>
              <th className="pb-2 pr-3">Method</th>
              <th className="pb-2"></th>
            </tr>
          </thead>
          <tbody>
            {pending.map(p => (
              <tr key={p.payment_id} className="border-b border-slate-800 hover:bg-slate-800/50">
                <td className="py-2 pr-3">
                  <button
                    onClick={() => onSelect(p.payment_id)}
                    className="text-blue-400 hover:text-blue-300 font-mono text-xs"
                  >
                    {p.payment_id.slice(0, 12)}...
                  </button>
                </td>
                <td className="py-2 pr-3 font-mono text-white">{formatINR(p.amount)}</td>
                <td className="py-2 pr-3 text-slate-300">{p.cause?.replace(/_/g, ' ')}</td>
                <td className="py-2 pr-3">
                  <span className="px-2 py-0.5 bg-amber-900/30 text-amber-300 rounded text-xs">
                    {p.recommended_action?.replace(/_/g, ' ')}
                  </span>
                </td>
                <td className="py-2 pr-3 text-center">{p.attempt_number}</td>
                <td className="py-2 pr-3 text-xs text-slate-400">{p.payment_method?.replace(/_/g, ' ')}</td>
                <td className="py-2 text-right space-x-2">
                  <button
                    onClick={() => onApprove(p.payment_id)}
                    disabled={approving}
                    className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-600 text-white text-xs rounded transition"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => onReject(p.payment_id)}
                    disabled={approving}
                    className="px-3 py-1 bg-red-600/50 hover:bg-red-500 disabled:bg-slate-600 text-white text-xs rounded transition"
                  >
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

function PaymentsTable({ payments, onSelect }) {
  const [filter, setFilter] = useState({ status: '', cause: '', method: '' })
  const [sortBy, setSortBy] = useState('amount')
  const [sortDir, setSortDir] = useState('desc')

  const filtered = (payments || []).filter(p => {
    if (filter.status && p.status !== filter.status) return false
    if (filter.cause && p.diagnosed_cause !== filter.cause) return false
    if (filter.method && p.payment_method !== filter.method) return false
    return true
  })

  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortBy], bv = b[sortBy]
    if (typeof av === 'number' && typeof bv === 'number') {
      return sortDir === 'desc' ? bv - av : av - bv
    }
    return sortDir === 'desc'
      ? String(bv).localeCompare(String(av))
      : String(av).localeCompare(String(bv))
  })

  const toggleSort = (col) => {
    if (sortBy === col) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortBy(col); setSortDir('desc') }
  }

  const causes = [...new Set(payments?.map(p => p.diagnosed_cause) || [])]
  const methods = [...new Set(payments?.map(p => p.payment_method) || [])]
  const statuses = [...new Set(payments?.map(p => p.status) || [])]

  return (
    <div className="space-y-4">
      <div className="flex gap-3 flex-wrap">
        <select
          value={filter.status}
          onChange={e => setFilter(f => ({ ...f, status: e.target.value }))}
          className="bg-slate-800 border border-slate-700 text-sm rounded px-2 py-1 text-slate-300"
        >
          <option value="">All statuses</option>
          {statuses.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
        </select>
        <select
          value={filter.cause}
          onChange={e => setFilter(f => ({ ...f, cause: e.target.value }))}
          className="bg-slate-800 border border-slate-700 text-sm rounded px-2 py-1 text-slate-300"
        >
          <option value="">All causes</option>
          {causes.sort().map(c => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
        </select>
        <select
          value={filter.method}
          onChange={e => setFilter(f => ({ ...f, method: e.target.value }))}
          className="bg-slate-800 border border-slate-700 text-sm rounded px-2 py-1 text-slate-300"
        >
          <option value="">All methods</option>
          {methods.sort().map(m => <option key={m} value={m}>{m.replace(/_/g, ' ')}</option>)}
        </select>
        <span className="text-xs text-slate-500 self-center ml-auto">{sorted.length} payments</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-400 border-b border-slate-700">
              {[
                ['payment_id', 'Payment ID'],
                ['amount', 'Amount'],
                ['diagnosed_cause', 'Cause'],
                ['payment_method', 'Method'],
                ['status', 'Status'],
                ['final_outcome', 'Outcome'],
                ['net_recovered', 'Net Recovered'],
                ['total_attempts', 'Attempts'],
              ].map(([key, label]) => (
                <th
                  key={key}
                  className="pb-2 pr-3 cursor-pointer hover:text-slate-200"
                  onClick={() => toggleSort(key)}
                >
                  {label} {sortBy === key ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.slice(0, 100).map(p => (
              <tr key={p.payment_id} className="border-b border-slate-800 hover:bg-slate-800/50">
                <td className="py-2 pr-3">
                  <button
                    onClick={() => onSelect(p.payment_id)}
                    className="text-blue-400 hover:text-blue-300 font-mono text-xs"
                  >
                    {p.payment_id.slice(0, 12)}...
                  </button>
                </td>
                <td className="py-2 pr-3 font-mono text-white">{formatINR(p.amount)}</td>
                <td className="py-2 pr-3 text-slate-300 text-xs">{p.diagnosed_cause?.replace(/_/g, ' ')}</td>
                <td className="py-2 pr-3 text-xs text-slate-400">{p.payment_method?.replace(/_/g, ' ')}</td>
                <td className="py-2 pr-3"><StatusBadge status={p.status} /></td>
                <td className="py-2 pr-3"><OutcomeBadge outcome={p.final_outcome} /></td>
                <td className="py-2 pr-3 font-mono text-xs">
                  {p.net_recovered > 0
                    ? <span className="text-emerald-400">{formatINR(p.net_recovered)}</span>
                    : <span className="text-slate-500">{formatINR(p.net_recovered)}</span>}
                </td>
                <td className="py-2 pr-3 text-center">{p.total_attempts}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sorted.length > 100 && (
          <p className="text-xs text-slate-500 mt-2 text-center">Showing first 100 of {sorted.length}</p>
        )}
      </div>
    </div>
  )
}

function DetailView({ detail, onBack, onApprove, onReject }) {
  if (!detail) return null

  const { payment, diagnosis, status, final_outcome, amount_recovered, action_cost, net_recovered, attempt_history, events, pending_action } = detail

  return (
    <div className="space-y-6">
      <button onClick={onBack} className="text-sm text-blue-400 hover:text-blue-300">&larr; Back</button>

      <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
        <div className="flex justify-between items-start">
          <div>
            <h3 className="text-lg font-medium text-white font-mono">{payment.payment_id}</h3>
            <p className="text-sm text-slate-400 mt-1">
              {payment.customer_id} &middot; {payment.bank_name} &middot; {payment.payment_method.replace(/_/g, ' ')}
            </p>
          </div>
          <div className="text-right">
            <div className="text-2xl font-semibold text-white">{formatINR(payment.amount)}</div>
            <StatusBadge status={status} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard label="Diagnosed Cause" value={diagnosis.cause?.replace(/_/g, ' ')} sub={`${(diagnosis.confidence * 100).toFixed(0)}% confidence`} />
        <MetricCard label="Status" value={final_outcome?.replace(/_/g, ' ') || status?.replace(/_/g, ' ')} />
        <MetricCard label="Recovered" value={formatINR(amount_recovered)} />
        <MetricCard label="Net" value={formatINR(net_recovered)} sub={`cost: ${formatINR(action_cost)}`} />
      </div>

      <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-4 text-sm">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div><span className="text-slate-400">Category:</span> <span className="text-white">{payment.payment_category}</span></div>
          <div><span className="text-slate-400">Failure Code:</span> <span className="text-white font-mono">{payment.failure_reason_code}</span></div>
          <div><span className="text-slate-400">Failure Time:</span> <span className="text-white font-mono text-xs">{payment.failure_timestamp}</span></div>
          <div><span className="text-slate-400">Ground Truth:</span> <span className="text-white">{payment.ground_truth_cause?.replace(/_/g, ' ')}</span></div>
        </div>
      </div>

      {pending_action && (
        <div className="bg-amber-900/20 border border-amber-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-amber-300 mb-2">Pending Approval</h3>
          <p className="text-sm text-slate-300 mb-3">
            Recommended: <span className="text-amber-300 font-medium">{pending_action.recommended_action?.replace(/_/g, ' ')}</span>
            {' '}(attempt {pending_action.attempt_number})
          </p>
          <div className="space-x-3">
            <button
              onClick={() => onApprove(payment.payment_id)}
              className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded transition"
            >
              Approve
            </button>
            <button
              onClick={() => onReject(payment.payment_id)}
              className="px-4 py-1.5 bg-red-600/50 hover:bg-red-500 text-white text-sm rounded transition"
            >
              Reject
            </button>
          </div>
        </div>
      )}

      {attempt_history && attempt_history.length > 0 && (
        <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-slate-300 mb-3">Attempt Timeline</h3>
          <div className="space-y-3">
            {attempt_history.map((a, i) => (
              <div key={i} className="flex items-start gap-3">
                <div className={`mt-1 w-2 h-2 rounded-full flex-shrink-0 ${a.outcome === 'success' ? 'bg-emerald-400' : 'bg-red-400'}`} />
                <div className="flex-1">
                  <div className="flex justify-between">
                    <span className="text-sm text-white">
                      Attempt {a.attempt} &middot; {a.action?.replace(/_/g, ' ')}
                    </span>
                    <span className={`text-xs ${a.outcome === 'success' ? 'text-emerald-400' : 'text-red-400'}`}>
                      {a.outcome}
                    </span>
                  </div>
                  <div className="text-xs text-slate-500 mt-0.5">
                    {a.time} &middot; cost: ₹{a.cost?.toFixed(0)} &middot; recovered: ₹{(a.recovered || 0).toFixed(0)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {events && events.length > 0 && (
        <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-slate-300 mb-3">Audit Events ({events.length})</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-700">
                  <th className="pb-1 pr-2">Type</th>
                  <th className="pb-1 pr-2">Action</th>
                  <th className="pb-1 pr-2">Gate</th>
                  <th className="pb-1 pr-2">Success</th>
                  <th className="pb-1 pr-2">Recovered</th>
                  <th className="pb-1 pr-2">Cost</th>
                  <th className="pb-1">Time</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e, i) => (
                  <tr key={i} className="border-b border-slate-800">
                    <td className="py-1 pr-2 text-slate-400">{e.event_type}</td>
                    <td className="py-1 pr-2 text-slate-300">{e.action_type}</td>
                    <td className="py-1 pr-2 text-slate-400">{e.gate_mode}</td>
                    <td className="py-1 pr-2">
                      {e.outcome_success
                        ? <span className="text-emerald-400">yes</span>
                        : <span className="text-slate-500">no</span>}
                    </td>
                    <td className="py-1 pr-2 font-mono">{formatINR(e.amount_recovered)}</td>
                    <td className="py-1 pr-2 font-mono">{formatINR(e.action_cost)}</td>
                    <td className="py-1 font-mono text-slate-500">{e.sim_timestamp?.slice(0, 16)}</td>
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

function App() {
  const [tab, setTab] = useState('overview')
  const [overview, setOverview] = useState(null)
  const [pending, setPending] = useState([])
  const [payments, setPayments] = useState([])
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [approving, setApproving] = useState(false)
  const [batchRan, setBatchRan] = useState(false)
  const [error, setError] = useState(null)
  const [lastAction, setLastAction] = useState(null)

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
    } catch (e) {
      setError('Backend offline — start with: uvicorn backend.main:app --port 8000')
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const runBatch = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/run-batch`, { method: 'POST' })
      const data = await res.json()
      setBatchRan(true)
      setLastAction(`Batch complete: ${data.auto_approved} auto-approved, ${data.pending_approval} pending, ${data.gate_blocked} blocked, ${data.non_retryable} non-retryable`)
      await refresh()
    } catch (e) {
      setError('Failed to run batch — is the backend running?')
    }
    setLoading(false)
  }

  const approveAction = async (pid) => {
    setApproving(true)
    try {
      const res = await fetch(`${API}/approve/${pid}`, { method: 'POST' })
      const data = await res.json()
      if (data.outcome === 'recovered') {
        setLastAction(`${pid.slice(0, 12)}: recovered ${formatINR(data.amount_recovered)}`)
      } else if (data.next_pending) {
        setLastAction(`${pid.slice(0, 12)}: failed — new pending action (attempt ${data.next_pending.attempt_number}, ${data.next_pending.recommended_action})`)
      } else {
        setLastAction(`${pid.slice(0, 12)}: ${data.outcome}`)
      }
      await refresh()
      if (detail && detail.payment?.payment_id === pid) {
        const d = await fetch(`${API}/payments/${pid}`).then(r => r.json())
        setDetail(d)
      }
    } catch (e) {
      setError('Approve failed')
    }
    setApproving(false)
  }

  const rejectAction = async (pid) => {
    setApproving(true)
    try {
      await fetch(`${API}/reject/${pid}`, { method: 'POST' })
      setLastAction(`${pid.slice(0, 12)}: rejected`)
      await refresh()
      if (detail && detail.payment?.payment_id === pid) {
        const d = await fetch(`${API}/payments/${pid}`).then(r => r.json())
        setDetail(d)
      }
    } catch (e) {
      setError('Reject failed')
    }
    setApproving(false)
  }

  const approveAll = async () => {
    setApproving(true)
    try {
      const res = await fetch(`${API}/approve-all`, { method: 'POST' })
      const data = await res.json()
      const recovered = data.filter(d => d.outcome === 'recovered').length
      const failed = data.filter(d => d.outcome !== 'recovered').length
      setLastAction(`Approved all: ${recovered} recovered, ${failed} other outcomes`)
      await refresh()
    } catch (e) {
      setError('Approve all failed')
    }
    setApproving(false)
  }

  const selectPayment = async (pid) => {
    try {
      const d = await fetch(`${API}/payments/${pid}`).then(r => r.json())
      setDetail(d)
      setTab('detail')
    } catch (e) {
      setError('Failed to load payment detail')
    }
  }

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'approvals', label: `Approvals${pending.length > 0 ? ` (${pending.length})` : ''}` },
    { id: 'payments', label: 'All Payments' },
  ]

  return (
    <div className="min-h-screen bg-slate-900">
      <header className="border-b border-slate-700 bg-slate-900/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold text-white">AI Revenue Recovery</h1>
            <span className="text-xs text-slate-500 border border-slate-700 rounded px-1.5 py-0.5">Stage 8</span>
          </div>
          <div className="flex items-center gap-3">
            {lastAction && (
              <span className="text-xs text-emerald-400 max-w-md truncate">{lastAction}</span>
            )}
            <button
              onClick={runBatch}
              disabled={loading}
              className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-sm rounded transition"
            >
              {loading ? 'Running...' : 'Run Batch'}
            </button>
          </div>
        </div>
      </header>

      {error && (
        <div className="max-w-7xl mx-auto px-4 mt-3">
          <div className="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm text-red-300">
            {error}
          </div>
        </div>
      )}

      <div className="max-w-7xl mx-auto px-4 mt-4">
        <nav className="flex gap-1 border-b border-slate-700 mb-6">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => { setTab(t.id); setDetail(null) }}
              className={`px-4 py-2 text-sm transition border-b-2 -mb-px ${
                tab === t.id
                  ? 'border-blue-400 text-blue-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        {tab === 'detail' && detail ? (
          <DetailView
            detail={detail}
            onBack={() => setTab('payments')}
            onApprove={approveAction}
            onReject={rejectAction}
          />
        ) : tab === 'overview' ? (
          <OverviewTab overview={overview} onRefresh={refresh} />
        ) : tab === 'approvals' ? (
          <ApprovalQueue
            pending={pending}
            onApprove={approveAction}
            onReject={rejectAction}
            onApproveAll={approveAll}
            onSelect={selectPayment}
            approving={approving}
          />
        ) : tab === 'payments' ? (
          <PaymentsTable payments={payments} onSelect={selectPayment} />
        ) : null}
      </div>
    </div>
  )
}

export default App
