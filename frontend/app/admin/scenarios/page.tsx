"use client";

import { FormEvent, useEffect, useState } from "react";
import { Shell } from "../../../components/Shell";
import { api, Me } from "../../../lib/api";
import { AUDIENCE_LABEL, TYPE_LABEL, triggerText } from "../../../lib/release";

type Option = { code: string; label: string };
type Item = {
  id: number; code: string; sequence: number; item_type: string; title: string; audience: string;
  trigger_type: string; trigger_day: string | null; trigger_time: string | null; trigger_module_code: string | null;
  trigger_lesson_state: string | null; trigger_after_code: string | null; inject_code: string | null;
  document_block: string | null; body: string; time_limit_minutes: number | null; instrument_code: string | null;
  scored: boolean; answer_for_code: string | null; instructor_notes: string;
};
type Version = {
  id: number; case_code: string; case_title: string; version_label: string; approval_status: string; locked: boolean;
  item_count: number; pending_approval_id: number | null; cohorts_using: string[];
};
type Detail = Version & { plan_sha256: string; items: Item[]; injects: Option[]; document_blocks: Option[]; instruments: Option[]; modules: Option[] };
type Draft = Omit<Item, "id"> & { id?: number };

const blank: Draft = {
  code: "", sequence: 100, item_type: "challenge", title: "", audience: "all_students", trigger_type: "manual",
  trigger_day: null, trigger_time: null, trigger_module_code: null, trigger_lesson_state: null, trigger_after_code: null,
  inject_code: null, document_block: null, body: "", time_limit_minutes: null, instrument_code: null, scored: false,
  answer_for_code: null, instructor_notes: "",
};

export default function Scenarios() {
  const [me, setMe] = useState<Me | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [cloneLabel, setCloneLabel] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const roles = me?.global_roles ?? [];
  const canAuthor = roles.includes("curriculum_editor") || roles.includes("program_admin");
  const canApprove = roles.includes("content_approver");
  const editable = !!detail && !detail.locked && detail.approval_status === "draft" && canAuthor;

  async function loadVersions() { setVersions(await api<Version[]>("/api/admin/scenario-versions")); }
  useEffect(() => {
    api<Me>("/api/me").then(setMe).catch(() => undefined);
    loadVersions().catch((e) => setError((e as Error).message));
  }, []);

  async function run(action: () => Promise<Detail | void>, success: string) {
    setError(""); setMessage("");
    try {
      const result = await action();
      if (result) setDetail(result);
      setMessage(success);
      await loadVersions();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    }
  }

  const open = (id: number) => { setDraft(null); run(() => api<Detail>(`/api/admin/scenario-versions/${id}`), ""); };

  async function saveItem(event: FormEvent) {
    event.preventDefault();
    if (!detail || !draft) return;
    const { id, ...body } = draft;
    const ok = await run(() => api<Detail>(
      id ? `/api/admin/scenario-versions/${detail.id}/items/${id}` : `/api/admin/scenario-versions/${detail.id}/items`,
      { method: id ? "PUT" : "POST", body: JSON.stringify(body) }), id ? "Item updated." : "Item added.");
    if (ok) setDraft(null);
  }

  async function decide(decision: "approved" | "rejected") {
    if (!detail?.pending_approval_id) return;
    await run(async () => {
      await api(`/api/admin/approvals/${detail.pending_approval_id}/decision`, { method: "POST", body: JSON.stringify({ decision, note: "Reviewed in scenario console" }) });
      return api<Detail>(`/api/admin/scenario-versions/${detail.id}`);
    }, decision === "approved" ? "Release plan approved and locked." : "Release plan returned to draft.");
  }

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => draft && setDraft({ ...draft, [key]: value });
  const status = (v: Version) => v.approval_status === "approved" ? "success" : v.approval_status === "pending" ? "warning" : "neutral";

  return (
    <Shell>
      <header className="page-header">
        <div>
          <div className="eyebrow">Curriculum governance</div>
          <h1>Scenarios and release plans</h1>
          <p className="lede">Define every piece of material a cohort can receive — evidence, documents, challenges, debriefs and answer keys — who sees it, and what opens it. Plans are approved as a package and locked; change an approved plan by cloning a new version.</p>
        </div>
      </header>
      {message && <div className="notice" role="status">{message}</div>}
      {error && <div className="error" role="alert">{error}</div>}

      <div className="split">
        <section className="card">
          <h2>Scenario versions</h2>
          <nav aria-label="Scenario versions">
            {versions.map((v) => (
              <button key={v.id} className="btn secondary" aria-current={detail?.id === v.id ? "true" : undefined} style={{ width: "100%", justifyContent: "space-between", marginTop: 8 }} onClick={() => open(v.id)}>
                <span>{v.case_code} v{v.version_label}</span>
                <span className={`status ${status(v)}`}>{v.approval_status}</span>
              </button>
            ))}
          </nav>
        </section>

        <div>
          {!detail && <section className="card empty-state"><p className="muted">Select a scenario version.</p></section>}
          {detail && (
            <>
              <section className="card">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <div>
                    <div className="eyebrow">{detail.case_code} · version {detail.version_label}</div>
                    <h2>{detail.case_title}</h2>
                    <p className="muted">
                      {detail.items.length} items · {detail.locked ? "locked" : "editable"} · plan hash {detail.plan_sha256.slice(0, 12)}…
                      {detail.cohorts_using.length > 0 && <> · used by {detail.cohorts_using.join(", ")}</>}
                    </p>
                  </div>
                  <span className={`status ${status(detail)}`}>{detail.approval_status}</span>
                </div>
                <div className="actions">
                  {editable && <button className="btn" onClick={() => setDraft({ ...blank })}>Add item</button>}
                  {editable && <button className="btn secondary" onClick={() => run(() => api<Detail>(`/api/admin/scenario-versions/${detail.id}/submit`, { method: "POST" }), "Submitted for approval. Editing is locked while it is reviewed.")}>Submit for approval</button>}
                  {canApprove && detail.pending_approval_id && <>
                    <button className="btn" onClick={() => decide("approved")}>Approve release plan</button>
                    <button className="btn danger" onClick={() => decide("rejected")}>Return to draft</button>
                  </>}
                </div>
                {canAuthor && (
                  <form className="row" onSubmit={(e) => { e.preventDefault(); run(() => api<Detail>(`/api/admin/scenario-versions/${detail.id}/clone`, { method: "POST", body: JSON.stringify({ version_label: cloneLabel }) }), `Version ${cloneLabel} created as an editable draft.`).then((ok) => ok && setCloneLabel("")); }}>
                    <label className="field" style={{ margin: 0 }}>
                      <span className="sr-only">New version label</span>
                      <input placeholder="New version label, e.g. 1.1" value={cloneLabel} onChange={(e) => setCloneLabel(e.target.value)} pattern="[0-9A-Za-z][0-9A-Za-z.\-]{0,15}" required />
                    </label>
                    <button className="btn secondary" style={{ marginTop: 0 }} type="submit">Clone to new version</button>
                  </form>
                )}
              </section>

              {draft && (
                <section className="card">
                  <h2>{draft.id ? `Edit ${draft.code}` : "New release item"}</h2>
                  <form onSubmit={saveItem}>
                    <div className="form-grid">
                      <label className="field">Item code
                        <input value={draft.code} onChange={(e) => set("code", e.target.value.toUpperCase())} pattern="[A-Z0-9][A-Z0-9\-]{1,31}" required />
                      </label>
                      <label className="field">Type
                        <select value={draft.item_type} onChange={(e) => set("item_type", e.target.value)}>
                          {Object.entries(TYPE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                      </label>
                      <label className="field">Title
                        <input value={draft.title} onChange={(e) => set("title", e.target.value)} required />
                      </label>
                      <label className="field">Order
                        <input type="number" min={0} value={draft.sequence} onChange={(e) => set("sequence", Number(e.target.value))} />
                      </label>
                      {(draft.item_type === "challenge" || draft.item_type === "debrief") && (
                        <label className="field">Audience
                          <select value={draft.audience} onChange={(e) => set("audience", e.target.value)}>
                            <option value="all_students">All students</option>
                            <option value="investigator">Investigators only</option>
                            <option value="analyst">Analysts only</option>
                          </select>
                        </label>
                      )}
                      {draft.item_type === "evidence_inject" && (
                        <label className="field">Inject
                          <select value={draft.inject_code ?? ""} onChange={(e) => set("inject_code", e.target.value || null)} required>
                            <option value="">Select inject…</option>
                            {detail.injects.map((o) => <option key={o.code} value={o.code}>{o.code} — {o.label}</option>)}
                          </select>
                        </label>
                      )}
                      {draft.item_type === "document_block" && (
                        <label className="field">Document block
                          <select value={draft.document_block ?? ""} onChange={(e) => set("document_block", e.target.value || null)} required>
                            <option value="">Select block…</option>
                            {detail.document_blocks.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
                          </select>
                        </label>
                      )}
                      {draft.item_type === "answer_key" && (
                        <label className="field">Answer for
                          <select value={draft.answer_for_code ?? ""} onChange={(e) => set("answer_for_code", e.target.value || null)}>
                            <option value="">(general)</option>
                            {detail.items.filter((i) => i.item_type === "challenge").map((i) => <option key={i.code} value={i.code}>{i.code}</option>)}
                          </select>
                        </label>
                      )}
                    </div>

                    {draft.item_type !== "answer_key" && (
                      <div className="form-grid">
                        <label className="field">Opens
                          <select value={draft.trigger_type} onChange={(e) => set("trigger_type", e.target.value)}>
                            <option value="manual">When the instructor releases it</option>
                            <option value="scheduled">At a scheduled course time</option>
                            <option value="lesson_gate">At a lesson stage</option>
                            <option value="after_item">After another item</option>
                          </select>
                        </label>
                        {draft.trigger_type === "scheduled" && <>
                          <label className="field">Course day
                            <select value={draft.trigger_day ?? ""} onChange={(e) => set("trigger_day", e.target.value || null)} required>
                              <option value="">Day…</option>{["Mon", "Tue", "Wed", "Thu", "Fri"].map((d) => <option key={d}>{d}</option>)}
                            </select>
                          </label>
                          <label className="field">Local time
                            <input type="time" value={draft.trigger_time ?? ""} onChange={(e) => set("trigger_time", e.target.value || null)} required />
                          </label>
                        </>}
                        {draft.trigger_type === "lesson_gate" && <>
                          <label className="field">Module
                            <select value={draft.trigger_module_code ?? ""} onChange={(e) => set("trigger_module_code", e.target.value || null)} required>
                              <option value="">Module…</option>{detail.modules.map((o) => <option key={o.code} value={o.code}>{o.code} — {o.label}</option>)}
                            </select>
                          </label>
                          <label className="field">Stage
                            <select value={draft.trigger_lesson_state ?? ""} onChange={(e) => set("trigger_lesson_state", e.target.value || null)} required>
                              <option value="">Stage…</option><option value="released">released</option><option value="taught">taught</option>
                            </select>
                          </label>
                        </>}
                        {draft.trigger_type === "after_item" && (
                          <label className="field">After item
                            <select value={draft.trigger_after_code ?? ""} onChange={(e) => set("trigger_after_code", e.target.value || null)} required>
                              <option value="">Item…</option>
                              {detail.items.filter((i) => i.code !== draft.code && i.item_type !== "answer_key").map((i) => <option key={i.code} value={i.code}>{i.code}</option>)}
                            </select>
                          </label>
                        )}
                      </div>
                    )}

                    {draft.item_type === "challenge" && (
                      <div className="form-grid">
                        <label className="field">Time limit (minutes, optional)
                          <input type="number" min={1} max={600} value={draft.time_limit_minutes ?? ""} onChange={(e) => set("time_limit_minutes", e.target.value ? Number(e.target.value) : null)} />
                        </label>
                        <label className="field">Assessment instrument (optional)
                          <select value={draft.instrument_code ?? ""} onChange={(e) => set("instrument_code", e.target.value || null)}>
                            <option value="">None (practice)</option>
                            {detail.instruments.map((o) => <option key={o.code} value={o.code}>{o.code} — {o.label}</option>)}
                          </select>
                        </label>
                        <label className="check-row" style={{ alignSelf: "center" }}>
                          <input type="checkbox" checked={draft.scored} onChange={(e) => set("scored", e.target.checked)} /> Scored (needs assessment authorization)
                        </label>
                      </div>
                    )}
                    {(draft.item_type === "challenge" || draft.item_type === "debrief" || draft.item_type === "answer_key") && (
                      <label className="field">{draft.item_type === "answer_key" ? "Answer notes (staff only)" : "Content students will see"}
                        <textarea value={draft.body} onChange={(e) => set("body", e.target.value)} required />
                      </label>
                    )}
                    <label className="field">Instructor notes (staff only, optional)
                      <textarea style={{ minHeight: 70 }} value={draft.instructor_notes} onChange={(e) => set("instructor_notes", e.target.value)} />
                    </label>
                    <div className="row">
                      <button className="btn" type="submit">{draft.id ? "Save item" : "Add item"}</button>
                      <button className="btn secondary" type="button" onClick={() => setDraft(null)}>Cancel</button>
                    </div>
                  </form>
                </section>
              )}

              <section className="card">
                <h2>Release plan</h2>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Item</th><th>Type</th><th>Audience</th><th>Opens</th><th>Details</th>{editable && <th />}</tr></thead>
                    <tbody>
                      {detail.items.map((i) => (
                        <tr key={i.id}>
                          <td><strong>{i.code}</strong><div className="muted">{i.title}</div></td>
                          <td><span className={`status ${i.item_type === "answer_key" ? "danger" : "neutral"}`}>{TYPE_LABEL[i.item_type]}</span></td>
                          <td>{AUDIENCE_LABEL[i.audience]}</td>
                          <td>{i.item_type === "answer_key" ? <span className="muted">Never released to students</span> : triggerText(i)}</td>
                          <td className="muted">
                            {i.inject_code && <>Inject {i.inject_code}</>}
                            {i.document_block && <>Block “{i.document_block}”</>}
                            {i.answer_for_code && <>Answers {i.answer_for_code}</>}
                            {i.time_limit_minutes && <>{i.time_limit_minutes} min </>}
                            {i.scored && <span className="status warning">scored {i.instrument_code}</span>}
                          </td>
                          {editable && (
                            <td>
                              <div className="actions">
                                <button className="btn secondary" onClick={() => { const { id, ...rest } = i; setDraft({ ...rest, id }); }}>Edit</button>
                                <button className="btn danger" onClick={() => run(() => api<Detail>(`/api/admin/scenario-versions/${detail.id}/items/${i.id}`, { method: "DELETE" }), `${i.code} removed.`)}>Remove</button>
                              </div>
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </Shell>
  );
}
