"use client";

import { FormEvent, useEffect, useState } from "react";
import { Shell } from "../../../components/Shell";
import { api, Me } from "../../../lib/api";

type CohortRole = { membership_id: number; cohort_code: string; role: string; pathway: string | null; status: string };
type AdminUser = {
  id: number; username: string; display_name: string; email: string; active: boolean; is_dev_persona: boolean;
  global_roles: string[]; cohort_roles: CohortRole[]; credential_state: string; last_login_at: string | null;
  locked_until: string | null; has_active_session: boolean; setup_link_expires_at: string | null;
};
type SetupLink = { setup_path: string; expires_in_seconds: number; notice: string };

const ROLES: [string, string][] = [
  ["program_admin", "Program Administrator"],
  ["secops_admin", "Security/Operations Administrator"],
  ["curriculum_editor", "Curriculum Editor"],
  ["content_approver", "Content Approver"],
];
const STATE: Record<string, [string, string]> = {
  active: ["Active", "success"],
  locked: ["Locked", "danger"],
  not_set_up: ["Not set up", "warning"],
  setup_pending: ["Setup link sent", "warning"],
  dev_persona: ["Dev persona", "neutral"],
};
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "—");

export default function UserAdministration() {
  const [me, setMe] = useState<Me | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [link, setLink] = useState<{ user: string; url: string; notice: string } | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [roleDraft, setRoleDraft] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const [form, setForm] = useState({ username: "", display_name: "", email: "", global_roles: [] as string[] });

  const isAdmin = me?.global_roles.includes("program_admin") ?? false;

  async function refresh() {
    setUsers(await api<AdminUser[]>("/api/admin/users"));
  }

  useEffect(() => {
    api<Me>("/api/me").then(setMe).catch(() => undefined);
    refresh().catch((e) => setError((e as Error).message));
  }, []);

  async function run(action: () => Promise<unknown>, success: string) {
    setError("");
    setMessage("");
    try {
      await action();
      setMessage(success);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      await api("/api/admin/users", { method: "POST", body: JSON.stringify(form) });
      setForm({ username: "", display_name: "", email: "", global_roles: [] });
    }, "User created. Issue a setup link so they can activate their account.");
  }

  async function issueLink(user: AdminUser, purpose: "enroll" | "reset") {
    if (purpose === "reset" && !window.confirm(`Reset ${user.display_name}? Their current password and authenticator stop working immediately and all sessions end.`)) return;
    await run(async () => {
      const result = await api<SetupLink>(`/api/admin/users/${user.id}/setup-link`, {
        method: "POST", body: JSON.stringify({ purpose }),
      });
      setLink({ user: user.display_name, url: `${window.location.origin}${result.setup_path}`, notice: result.notice });
    }, purpose === "reset" ? "Credentials reset." : "Setup link issued.");
  }

  async function saveRoles(user: AdminUser) {
    await run(async () => {
      await api(`/api/admin/users/${user.id}/roles`, { method: "PUT", body: JSON.stringify({ roles: roleDraft }) });
      setEditing(null);
    }, "Roles updated.");
  }

  const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  const shown = users.filter((u) => `${u.display_name} ${u.username} ${u.email}`.toLowerCase().includes(filter.toLowerCase()));

  return (
    <Shell>
      <header className="page-header">
        <div>
          <div className="eyebrow">Administration</div>
          <h1>Users and access</h1>
          <p className="lede">Create accounts, assign global roles, and issue one-time setup or reset links. Cohort roles are managed on the Cohorts page.</p>
        </div>
      </header>
      {message && <div className="notice" role="status">{message}</div>}
      {error && <div className="error" role="alert">{error}</div>}

      {link && (
        <section className="card" aria-live="polite">
          <h2>One-time link for {link.user}</h2>
          <p className="muted">{link.notice}</p>
          <div className="secret-box">{link.url}</div>
          <div className="row">
            <button className="btn" onClick={() => navigator.clipboard.writeText(link.url).then(() => setMessage("Link copied."))}>Copy link</button>
            <button className="btn secondary" onClick={() => setLink(null)}>I have delivered it — hide</button>
          </div>
        </section>
      )}

      {isAdmin && (
        <section className="card">
          <h2>Create user</h2>
          <form onSubmit={create}>
            <div className="form-grid">
              <label className="field">Username
                <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
                  pattern="[a-zA-Z0-9][a-zA-Z0-9._\-]{2,63}" title="3–64 letters, digits, dots, dashes or underscores" required />
              </label>
              <label className="field">Display name
                <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required />
              </label>
              <label className="field">Email
                <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
              </label>
            </div>
            <fieldset className="check-row" style={{ border: 0, padding: 0 }}>
              <legend className="muted" style={{ marginBottom: 6 }}>Global roles (optional — students and instructors need none)</legend>
              {ROLES.map(([value, label]) => (
                <label key={value}>
                  <input type="checkbox" checked={form.global_roles.includes(value)}
                    onChange={() => setForm({ ...form, global_roles: toggle(form.global_roles, value) })} />
                  {label}
                </label>
              ))}
            </fieldset>
            <button className="btn" type="submit">Create user</button>
          </form>
        </section>
      )}

      <section className="card">
        <div className="row spaced" style={{ justifyContent: "space-between" }}>
          <h2>All users ({users.length})</h2>
          <label className="field" style={{ margin: 0, minWidth: 240 }}>
            <span className="sr-only">Filter users</span>
            <input placeholder="Filter by name, username or email" value={filter} onChange={(e) => setFilter(e.target.value)} />
          </label>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>User</th><th>Account</th><th>Global roles</th><th>Cohort roles</th><th>Last sign-in</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {shown.map((u) => {
                const [label, tone] = STATE[u.credential_state] ?? [u.credential_state, "neutral"];
                return (
                  <tr key={u.id}>
                    <td>
                      <strong>{u.display_name}</strong>
                      <div className="muted">{u.username} · {u.email}</div>
                    </td>
                    <td>
                      {u.active ? <span className={`status ${tone}`}>{label}</span> : <span className="status danger">Deactivated</span>}
                      {u.locked_until && <div className="muted">until {when(u.locked_until)}</div>}
                    </td>
                    <td>
                      {editing === u.id ? (
                        <div>
                          <div className="check-row">
                            {ROLES.map(([value, label]) => (
                              <label key={value}>
                                <input type="checkbox" checked={roleDraft.includes(value)} onChange={() => setRoleDraft(toggle(roleDraft, value))} />
                                {label}
                              </label>
                            ))}
                          </div>
                          <div className="actions">
                            <button className="btn" onClick={() => saveRoles(u)}>Save</button>
                            <button className="btn secondary" onClick={() => setEditing(null)}>Cancel</button>
                          </div>
                        </div>
                      ) : (
                        u.global_roles.map((r) => ROLES.find(([v]) => v === r)?.[1] ?? r).join(", ") || <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      {u.cohort_roles.length === 0 && <span className="muted">—</span>}
                      {u.cohort_roles.map((c) => (
                        <div key={c.membership_id} className={c.status === "withdrawn" ? "muted" : ""}>
                          {c.cohort_code} · {c.role}{c.pathway ? ` (${c.pathway})` : ""}{c.status === "withdrawn" ? " · withdrawn" : ""}
                        </div>
                      ))}
                    </td>
                    <td>{when(u.last_login_at)}</td>
                    <td>
                      <div className="actions">
                        {isAdmin && !u.is_dev_persona && u.active && (
                          u.credential_state === "active" || u.credential_state === "locked"
                            ? <button className="btn secondary" onClick={() => issueLink(u, "reset")}>Reset credentials</button>
                            : <button className="btn" onClick={() => issueLink(u, "enroll")}>Issue setup link</button>
                        )}
                        {isAdmin && editing !== u.id && (
                          <button className="btn secondary" onClick={() => { setEditing(u.id); setRoleDraft(u.global_roles); }}>Edit roles</button>
                        )}
                        {u.credential_state === "locked" && (
                          <button className="btn secondary" onClick={() => run(() => api(`/api/admin/users/${u.id}/unlock`, { method: "POST" }), "Account unlocked.")}>Unlock</button>
                        )}
                        {u.has_active_session && (
                          <button className="btn secondary" onClick={() => run(() => api(`/api/admin/users/${u.id}/revoke-sessions`, { method: "POST" }), "Sessions ended.")}>End sessions</button>
                        )}
                        {isAdmin && u.id !== me?.id && (
                          <button className={`btn ${u.active ? "danger" : "secondary"}`}
                            onClick={() => run(() => api(`/api/admin/users/${u.id}`, { method: "PATCH", body: JSON.stringify({ active: !u.active }) }),
                              u.active ? "User deactivated and signed out." : "User reactivated.")}>
                            {u.active ? "Deactivate" : "Reactivate"}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </Shell>
  );
}
