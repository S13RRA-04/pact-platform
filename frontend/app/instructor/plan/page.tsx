"use client";

import { Fragment, useEffect, useState } from "react";
import { Shell } from "../../../components/Shell";
import { api } from "../../../lib/api";
import { AUDIENCE_LABEL, STATE_TONE, TYPE_LABEL } from "../../../lib/release";

type StaffCohort = { id: number; code: string; name: string };
type PlanItem = {
  item_id: number; code: string; sequence: number; item_type: string; title: string; audience: string; trigger: string;
  state: string; due_at: string | null; released_at: string | null; released_by: string | null; withdrawn_at: string | null;
  reason: string | null; blocked_reason: string | null; scored: boolean; preview: string; instructor_notes: string;
};
type Plan = {
  cohort_id: number; cohort_code: string; timezone: string; case_code: string | null; scenario_version: string | null;
  approval_status: string | null; can_control: boolean; items: PlanItem[];
};

export default function ReleasePlan() {
  const [cohorts, setCohorts] = useState<StaffCohort[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [filter, setFilter] = useState("all");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load(id: number) {
    setError("");
    try { setPlan(await api<Plan>(`/api/cohorts/${id}/release-plan`)); } catch (e) { setError((e as Error).message); }
  }

  useEffect(() => {
    api<StaffCohort[]>("/api/staff/cohorts")
      .then((all) => { setCohorts(all); if (all[0]) load(all[0].id); })
      .catch((e) => setError((e as Error).message));
  }, []);

  async function act(item: PlanItem, action: string) {
    if (!plan) return;
    setError(""); setMessage("");
    try {
      setPlan(await api<Plan>(`/api/cohorts/${plan.cohort_id}/release-plan/${item.item_id}/${action}`, {
        method: "POST", body: JSON.stringify({ reason: reason || null }),
      }));
      setMessage(`${item.code}: ${action === "release" ? "released" : action === "withdraw" ? "withdrawn" : action === "hold" ? "on hold" : "resumed"}.`);
      setReason(""); setOpen(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "");
  const items = (plan?.items ?? []).filter((i) => filter === "all" || i.state === filter || (filter === "blocked" && i.blocked_reason));
  const counts = (s: string) => plan?.items.filter((i) => i.state === s).length ?? 0;

  return (
    <Shell>
      <header className="page-header">
        <div>
          <div className="eyebrow">Instructor tools</div>
          <h1>Release plan</h1>
          <p className="lede">Everything this cohort can receive, in order: what students already have, what opens next and why, and what is blocked. Releases notify students; withdrawals hide material and are recorded with a reason.</p>
        </div>
        {cohorts.length > 1 && (
          <label className="field" style={{ minWidth: 280 }}>Cohort
            <select value={plan?.cohort_id ?? ""} onChange={(e) => load(Number(e.target.value))}>
              {cohorts.map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
            </select>
          </label>
        )}
      </header>
      {message && <div className="notice" role="status">{message}</div>}
      {error && <div className="error" role="alert">{error}</div>}

      {plan && !plan.case_code && (
        <section className="card"><p className="muted">No scenario has been activated for {plan.cohort_code}. A program administrator activates an approved scenario version from the Cohorts page.</p></section>
      )}

      {plan?.case_code && (
        <>
          <section className="stats-grid">
            <div className="card stat-card"><div className="metric-label">Scenario</div><div className="metric">{plan.case_code}</div><div className="metric-detail">v{plan.scenario_version} · {plan.approval_status} · times in {plan.timezone}</div></div>
            <div className="card stat-card"><div className="metric-label">Released</div><div className="metric">{counts("released")} / {plan.items.length}</div><div className="metric-detail">{counts("withdrawn")} withdrawn</div></div>
            <div className="card stat-card"><div className="metric-label">Waiting</div><div className="metric">{counts("pending") + counts("held")}</div><div className="metric-detail">{counts("held")} on hold · {plan.items.filter((i) => i.blocked_reason).length} blocked</div></div>
          </section>
          {!plan.can_control && <div className="notice" role="status">You can view this plan; only instructors of the cohort can release or withdraw material.</div>}

          <section className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2>Timeline</h2>
              <label className="field" style={{ margin: 0 }}>
                <span className="sr-only">Filter items</span>
                <select value={filter} onChange={(e) => setFilter(e.target.value)}>
                  <option value="all">All items</option><option value="pending">Pending</option><option value="released">Released</option>
                  <option value="held">On hold</option><option value="withdrawn">Withdrawn</option><option value="blocked">Blocked</option>
                </select>
              </label>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Item</th><th>Type</th><th>Audience</th><th>Opens</th><th>Status</th><th>Actions</th></tr></thead>
                <tbody>
                  {items.map((i) => (
                    <Fragment key={i.item_id}>
                      <tr>
                        <td><strong>{i.code}</strong><div className="muted">{i.title}</div></td>
                        <td><span className={`status ${i.item_type === "answer_key" ? "danger" : "neutral"}`}>{TYPE_LABEL[i.item_type]}</span>{i.scored && <div className="muted">scored</div>}</td>
                        <td>{AUDIENCE_LABEL[i.audience]}</td>
                        <td>{i.trigger}{i.due_at && <div className="muted">{fmt(i.due_at)}</div>}</td>
                        <td>
                          <span className={`status ${STATE_TONE[i.state]}`}>{i.state === "held" ? "on hold" : i.state}</span>
                          {i.released_at && i.state === "released" && <div className="muted">{fmt(i.released_at)}{i.released_by ? ` · ${i.released_by}` : ""}</div>}
                          {i.reason && <div className="muted">“{i.reason}”</div>}
                          {i.blocked_reason && i.state !== "released" && <div className="muted" style={{ color: "var(--danger)" }}>Blocked: {i.blocked_reason}</div>}
                        </td>
                        <td>
                          <div className="actions">
                            <button className="btn secondary" aria-expanded={open === i.item_id} onClick={() => { setOpen(open === i.item_id ? null : i.item_id); setReason(""); }}>
                              {open === i.item_id ? "Close" : "Preview"}
                            </button>
                            {plan.can_control && i.item_type !== "answer_key" && (i.state === "pending" || i.state === "held" || i.state === "withdrawn") && (
                              <button className="btn" onClick={() => act(i, "release")}>{i.state === "withdrawn" ? "Re-release" : "Release now"}</button>
                            )}
                            {plan.can_control && i.state === "pending" && i.item_type !== "answer_key" && <button className="btn secondary" onClick={() => act(i, "hold")}>Hold</button>}
                            {plan.can_control && i.state === "held" && <button className="btn secondary" onClick={() => act(i, "resume")}>Resume</button>}
                            {plan.can_control && i.state === "released" && <button className="btn danger" onClick={() => { setOpen(i.item_id); setReason(""); }}>Withdraw…</button>}
                          </div>
                        </td>
                      </tr>
                      {open === i.item_id && (
                        <tr>
                          <td colSpan={6} style={{ background: "var(--bg)" }}>
                            <div className="eyebrow">{i.item_type === "answer_key" ? "Answer key — staff only" : "What students receive"}</div>
                            <p style={{ whiteSpace: "pre-wrap" }}>{i.preview || <span className="muted">No preview text.</span>}</p>
                            {i.instructor_notes && <p className="muted" style={{ whiteSpace: "pre-wrap" }}><strong>Instructor notes:</strong> {i.instructor_notes}</p>}
                            {plan.can_control && i.state === "released" && (
                              <div className="row">
                                <label className="field" style={{ margin: 0, minWidth: 320 }}>
                                  <span className="sr-only">Reason for withdrawing {i.code}</span>
                                  <input placeholder="Reason for withdrawing (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
                                </label>
                                <button className="btn danger" style={{ marginTop: 0 }} disabled={!reason.trim()} onClick={() => act(i, "withdraw")}>Withdraw from students</button>
                              </div>
                            )}
                            {plan.can_control && i.state === "pending" && (
                              <div className="row">
                                <label className="field" style={{ margin: 0, minWidth: 320 }}>
                                  <span className="sr-only">Note for {i.code}</span>
                                  <input placeholder="Optional note (recorded with a release or hold)" value={reason} onChange={(e) => setReason(e.target.value)} />
                                </label>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </Shell>
  );
}
