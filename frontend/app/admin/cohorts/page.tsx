"use client";

import { FormEvent, useEffect, useState } from "react";
import { Shell } from "../../../components/Shell";
import { CohortDetail, SquadManager } from "../../../components/SquadManager";
import { api } from "../../../lib/api";

type CohortSummary = Omit<CohortDetail, "members" | "squads">;
type UserOption = { id: number; display_name: string; username: string; active: boolean };

const emptyCohort = { code: "", name: "", start_date: "", end_date: "", timezone: "America/Chicago" };

export default function CohortAdministration() {
  const [cohorts, setCohorts] = useState<CohortSummary[]>([]);
  const [selected, setSelected] = useState<CohortDetail | null>(null);
  const [users, setUsers] = useState<UserOption[]>([]);
  const [form, setForm] = useState(emptyCohort);
  const [member, setMember] = useState({ user_id: "", role: "student", pathway: "investigator" });
  const [showWithdrawn, setShowWithdrawn] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function loadCohorts() {
    setCohorts(await api<CohortSummary[]>("/api/admin/cohorts"));
  }

  useEffect(() => {
    loadCohorts().catch((e) => setError((e as Error).message));
    api<UserOption[]>("/api/admin/users").then(setUsers).catch(() => undefined);
  }, []);

  async function run(action: () => Promise<CohortDetail>, success: string) {
    setError("");
    setMessage("");
    try {
      setSelected(await action());
      setMessage(success);
      await loadCohorts();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const open = (id: number) => run(() => api<CohortDetail>(`/api/admin/cohorts/${id}`), "");

  async function create(event: FormEvent) {
    event.preventDefault();
    await run(() => api<CohortDetail>("/api/admin/cohorts", { method: "POST", body: JSON.stringify(form) }), "Cohort created.");
    setForm(emptyCohort);
  }

  async function addMember(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    const body = { user_id: Number(member.user_id), role: member.role, pathway: member.role === "student" ? member.pathway : null };
    await run(() => api<CohortDetail>(`/api/admin/cohorts/${selected.id}/members`, { method: "POST", body: JSON.stringify(body) }), "Member added.");
  }

  const updateMember = (membershipId: number, body: object, success: string) =>
    selected && run(() => api<CohortDetail>(`/api/admin/cohorts/${selected.id}/members/${membershipId}`, {
      method: "PATCH", body: JSON.stringify(body),
    }), success);

  const members = selected?.members.filter((m) => showWithdrawn || m.status === "active") ?? [];
  const enrolledIds = new Set(selected?.members.filter((m) => m.status === "active").map((m) => m.user_id));

  return (
    <Shell>
      <header className="page-header">
        <div>
          <div className="eyebrow">Administration</div>
          <h1>Cohorts and enrollment</h1>
          <p className="lede">Create cohorts, enroll students with their assessed pathway, assign instructors and evaluators, and organize squads.</p>
        </div>
      </header>
      {message && <div className="notice" role="status">{message}</div>}
      {error && <div className="error" role="alert">{error}</div>}

      <div className="split">
        <div>
          <section className="card">
            <h2>Cohorts</h2>
            {cohorts.length === 0 && <p className="muted">No cohorts yet.</p>}
            <nav aria-label="Cohorts">
              {cohorts.map((c) => (
                <button key={c.id} className={`btn ${selected?.id === c.id ? "" : "secondary"}`}
                  style={{ width: "100%", justifyContent: "space-between", marginTop: 8 }}
                  aria-current={selected?.id === c.id ? "true" : undefined} onClick={() => open(c.id)}>
                  <span>{c.code}</span>
                  <span>{c.counts.student} students{c.status === "archived" ? " · archived" : ""}</span>
                </button>
              ))}
            </nav>
          </section>
          <section className="card">
            <h2>New cohort</h2>
            <form onSubmit={create}>
              <label className="field">Code
                <input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
                  placeholder="PACT-2027-01" pattern="[A-Z0-9][A-Z0-9\-]{2,31}" required />
              </label>
              <label className="field">Name
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </label>
              <div className="form-grid">
                <label className="field">Start
                  <input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} required />
                </label>
                <label className="field">End
                  <input type="date" value={form.end_date} min={form.start_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} required />
                </label>
              </div>
              <label className="field">Timezone (IANA)
                <input value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} required />
              </label>
              <button className="btn" type="submit">Create cohort</button>
            </form>
          </section>
        </div>

        <div>
          {!selected && <section className="card empty-state"><p className="muted">Select a cohort to manage its roster and squads.</p></section>}
          {selected && (
            <>
              <section className="card">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <div>
                    <div className="eyebrow">{selected.code} · curriculum v{selected.course_version}</div>
                    <h2>{selected.name}</h2>
                    <p className="muted">{selected.start_date} to {selected.end_date} · {selected.timezone} · {selected.counts.student} students, {selected.counts.instructor} instructors, {selected.counts.evaluator} evaluators</p>
                  </div>
                  <button className="btn secondary"
                    onClick={() => run(() => api<CohortDetail>(`/api/admin/cohorts/${selected.id}`, {
                      method: "PATCH", body: JSON.stringify({ status: selected.status === "active" ? "archived" : "active" }),
                    }), selected.status === "active" ? "Cohort archived." : "Cohort reactivated.")}>
                    {selected.status === "active" ? "Archive cohort" : "Reactivate cohort"}
                  </button>
                </div>
                <p className="muted">New cohorts start without a case or assignments; activating a scenario for a cohort is not yet available in the interface.</p>
              </section>

              <section className="card">
                <h2>Add member</h2>
                <form onSubmit={addMember}>
                  <div className="form-grid">
                    <label className="field">User
                      <select value={member.user_id} onChange={(e) => setMember({ ...member, user_id: e.target.value })} required>
                        <option value="">Select user…</option>
                        {users.filter((u) => u.active && !enrolledIds.has(u.id)).map((u) => (
                          <option key={u.id} value={u.id}>{u.display_name} ({u.username})</option>
                        ))}
                      </select>
                    </label>
                    <label className="field">Cohort role
                      <select value={member.role} onChange={(e) => setMember({ ...member, role: e.target.value })}>
                        <option value="student">Student</option>
                        <option value="instructor">Instructor</option>
                        <option value="evaluator">Evaluator</option>
                      </select>
                    </label>
                    {member.role === "student" && (
                      <label className="field">Assessed pathway
                        <select value={member.pathway} onChange={(e) => setMember({ ...member, pathway: e.target.value })}>
                          <option value="investigator">Investigator</option>
                          <option value="analyst">Intelligence Analyst</option>
                        </select>
                      </label>
                    )}
                    <div><button className="btn" type="submit">Add to cohort</button></div>
                  </div>
                </form>
              </section>

              <section className="card">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <h2>Roster</h2>
                  <label className="check-row"><input type="checkbox" checked={showWithdrawn} onChange={(e) => setShowWithdrawn(e.target.checked)} /> Show withdrawn</label>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Name</th><th>Role</th><th>Pathway</th><th>Squad</th><th>Status</th><th>Actions</th></tr></thead>
                    <tbody>
                      {members.map((m) => (
                        <tr key={m.membership_id}>
                          <td><strong>{m.display_name}</strong><div className="muted">{m.username}</div></td>
                          <td>{m.role}</td>
                          <td>
                            {m.role === "student" ? (
                              <label className="field" style={{ margin: 0 }}>
                                <span className="sr-only">Pathway for {m.display_name}</span>
                                <select value={m.pathway ?? ""} disabled={m.has_submissions || m.status !== "active"}
                                  title={m.has_submissions ? "Locked: the student has submitted work under this pathway" : undefined}
                                  onChange={(e) => updateMember(m.membership_id, { pathway: e.target.value }, "Pathway updated.")}>
                                  <option value="investigator">Investigator</option>
                                  <option value="analyst">Intelligence Analyst</option>
                                </select>
                              </label>
                            ) : <span className="muted">—</span>}
                          </td>
                          <td>{m.squad_name ?? <span className="muted">—</span>}</td>
                          <td><span className={`status ${m.status === "active" ? "success" : "neutral"}`}>{m.status}</span></td>
                          <td>
                            {m.status === "active"
                              ? <button className="btn secondary" style={{ marginTop: 0 }} onClick={() => updateMember(m.membership_id, { status: "withdrawn" }, "Member withdrawn. Their records are kept.")}>Withdraw</button>
                              : <button className="btn secondary" style={{ marginTop: 0 }} onClick={() => updateMember(m.membership_id, { status: "active" }, "Member reinstated.")}>Reinstate</button>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <SquadManager detail={selected} onChange={(d) => { setSelected(d); setMessage("Squads updated."); }} onError={setError} />
            </>
          )}
        </div>
      </div>
    </Shell>
  );
}
