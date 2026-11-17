"use client";

import { FormEvent, useState } from "react";
import { api } from "../lib/api";

export type Member = {
  membership_id: number; user_id: number; username: string; display_name: string; role: string;
  pathway: string | null; status: string; squad_id: number | null; squad_name: string | null; has_submissions: boolean;
};
export type Squad = { id: number; name: string; member_ids: number[] };
export type CohortDetail = {
  id: number; code: string; name: string; start_date: string; end_date: string; timezone: string; status: string;
  course_version: string; counts: Record<string, number>; members: Member[]; squads: Squad[];
};

/** Squad assignment for one cohort. Used by Program Administrators and by the cohort's instructors;
 * the server enforces who may call it. Each active student belongs to at most one squad. */
export function SquadManager({ detail, onChange, onError }: {
  detail: CohortDetail; onChange: (d: CohortDetail) => void; onError: (message: string) => void;
}) {
  const [name, setName] = useState("");
  const base = `/api/cohorts/${detail.id}/squads`;
  const students = detail.members.filter((m) => m.role === "student" && m.status === "active");
  const unassigned = students.filter((m) => !detail.squads.some((s) => s.member_ids.includes(m.user_id)));

  async function call(path: string, init: RequestInit) {
    try {
      onChange(await api<CohortDetail>(path, init));
    } catch (e) {
      onError((e as Error).message);
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    await call(base, { method: "POST", body: JSON.stringify({ name }) });
    setName("");
  }

  const setMembers = (squad: Squad, ids: number[]) =>
    call(`${base}/${squad.id}/members`, { method: "PUT", body: JSON.stringify({ user_ids: ids }) });

  return (
    <section className="card">
      <h2>Squads</h2>
      <p className="muted">Mix investigators and analysts in each squad where the roster allows. Moving a student here removes them from their previous squad.</p>
      <form className="row" onSubmit={create}>
        <label className="field" style={{ margin: 0 }}>
          <span className="sr-only">New squad name</span>
          <input placeholder="New squad name" value={name} onChange={(e) => setName(e.target.value)} maxLength={64} required />
        </label>
        <button className="btn" style={{ marginTop: 0 }} type="submit">Add squad</button>
      </form>
      {unassigned.length > 0 && (
        <p className="notice">Not in a squad: {unassigned.map((m) => `${m.display_name} (${m.pathway})`).join(", ")}</p>
      )}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Squad</th><th>Members</th><th>Add student</th><th /></tr></thead>
          <tbody>
            {detail.squads.map((squad) => {
              const members = students.filter((m) => squad.member_ids.includes(m.user_id));
              const candidates = students.filter((m) => !squad.member_ids.includes(m.user_id));
              return (
                <tr key={squad.id}>
                  <td><strong>{squad.name}</strong></td>
                  <td>
                    {members.length === 0 && <span className="muted">No members</span>}
                    {members.map((m) => (
                      <div key={m.user_id} className="row" style={{ gap: 6 }}>
                        <span>{m.display_name} <span className="muted">· {m.pathway}</span></span>
                        <button className="btn secondary" style={{ marginTop: 0, minHeight: 24, padding: "2px 7px" }}
                          aria-label={`Remove ${m.display_name} from ${squad.name}`}
                          onClick={() => setMembers(squad, squad.member_ids.filter((id) => id !== m.user_id))}>Remove</button>
                      </div>
                    ))}
                  </td>
                  <td>
                    <label className="field" style={{ margin: 0 }}>
                      <span className="sr-only">Add a student to {squad.name}</span>
                      <select value="" onChange={(e) => e.target.value && setMembers(squad, [...squad.member_ids, Number(e.target.value)])}>
                        <option value="">Add student…</option>
                        {candidates.map((m) => (
                          <option key={m.user_id} value={m.user_id}>
                            {m.display_name} ({m.pathway}){m.squad_name ? ` — in ${m.squad_name}` : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                  </td>
                  <td>
                    <button className="btn danger" style={{ marginTop: 0 }} onClick={() => call(`${base}/${squad.id}`, { method: "DELETE" })}>Delete</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
