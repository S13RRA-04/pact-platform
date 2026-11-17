"use client";

import { useEffect, useMemo, useState } from "react";
import { Shell } from "../../components/Shell";
import { api, Me } from "../../lib/api";
import { downloadMaterial, fileKind, kb, Material } from "../../lib/materials";

/** Course materials. Students: packets released to their cohort. Staff: approved student and instructor-only
 * materials for preparation. Downloads use short-lived links that the server re-checks when used. */
export default function Materials() {
  const [me, setMe] = useState<Me | null>(null);
  const [student, setStudent] = useState<Material[] | null>(null);
  const [staff, setStaff] = useState<Material[] | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<Me>("/api/me").then((m) => {
      setMe(m);
      if (m.memberships.some((x) => x.role === "student")) api<Material[]>("/api/student/materials").then(setStudent).catch((e) => setError(e.message));
      const isStaff = m.memberships.some((x) => x.role !== "student") || m.global_roles.some((r) => ["program_admin", "curriculum_editor", "content_approver"].includes(r));
      if (isStaff) api<Material[]>("/api/staff/materials").then(setStaff).catch((e) => setError(e.message));
    }).catch((e) => setError(e.message));
  }, []);

  const download = (id: number) => downloadMaterial(id).catch((e) => setError((e as Error).message));
  const shownStaff = useMemo(() => (staff ?? []).filter((m) => `${m.document_code} ${m.title}`.toLowerCase().includes(filter.toLowerCase())), [staff, filter]);

  const table = (rows: Material[], showRelease: boolean) => (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Document</th><th>Type</th>{showRelease ? <th>Released</th> : <th>Audience</th>}<th /></tr></thead>
        <tbody>
          {rows.map((m) => (
            <tr key={`${m.id}-${m.cohort_code ?? ""}`}>
              <td><strong>{m.title}</strong><div className="muted">{m.document_code}{m.release_block ? ` · ${m.release_block}` : ""}</div></td>
              <td>{fileKind(m.media_type)} · {kb(m.byte_size)}</td>
              {showRelease
                ? <td>{m.released_at ? new Date(m.released_at).toLocaleString() : "—"}{m.cohort_code && <div className="muted">{m.cohort_code}</div>}</td>
                : <td><span className={`status ${m.audience === "instructor" ? "danger" : "neutral"}`}>{m.audience === "instructor" ? "Instructor only" : "Student material"}</span></td>}
              <td><button className="btn secondary" onClick={() => download(m.id)} aria-label={`Download ${m.title}`}>Download</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <Shell>
      <header className="page-header">
        <div>
          <div className="eyebrow">Case HARBORLINE</div>
          <h1>Course materials</h1>
          <p className="lede">Exercise packets and staged case documents appear here as your instructor releases them. Work from the released material only.</p>
        </div>
      </header>
      {error && <div className="error" role="alert">{error}</div>}

      {student && (
        <section className="card">
          <h2>Released to you ({student.length})</h2>
          {student.length === 0
            ? <p className="muted">Nothing has been released yet. Packets open as each exercise begins.</p>
            : table(student, true)}
        </section>
      )}

      {staff && (
        <section className="card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div>
              <h2>Instructor and preparation materials ({staff.length})</h2>
              <p className="muted">Instructor-only items (master, annotated key, knowledge checks, full source dossier) must not be shared with students. Release student material through the Release Plan.</p>
            </div>
            <label className="field" style={{ margin: 0, minWidth: 260 }}>
              <span className="sr-only">Filter materials</span>
              <input placeholder="Filter by code or title" value={filter} onChange={(e) => setFilter(e.target.value)} />
            </label>
          </div>
          {table(shownStaff, false)}
        </section>
      )}
      {me && !student && !staff && !error && <section className="card"><p className="muted">No course materials are available for your role.</p></section>}
    </Shell>
  );
}
