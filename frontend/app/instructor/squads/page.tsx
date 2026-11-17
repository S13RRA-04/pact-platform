"use client";

import { useEffect, useState } from "react";
import { Shell } from "../../../components/Shell";
import { CohortDetail, SquadManager } from "../../../components/SquadManager";
import { api } from "../../../lib/api";

type StaffCohort = { id: number; code: string; name: string; my_roles: string[] };

export default function InstructorSquads() {
  const [cohorts, setCohorts] = useState<StaffCohort[]>([]);
  const [detail, setDetail] = useState<CohortDetail | null>(null);
  const [error, setError] = useState("");

  async function load(id: number) {
    setError("");
    try {
      setDetail(await api<CohortDetail>(`/api/cohorts/${id}/squads`));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    api<StaffCohort[]>("/api/staff/cohorts")
      .then((all) => {
        const taught = all.filter((c) => c.my_roles.includes("instructor"));
        setCohorts(taught);
        if (taught[0]) load(taught[0].id);
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  return (
    <Shell>
      <header className="page-header">
        <div>
          <div className="eyebrow">Instructor tools</div>
          <h1>Squad assignments</h1>
          <p className="lede">Organize students in the cohorts you teach into investigator–analyst squads. Enrollment changes are made by your program administrator.</p>
        </div>
      </header>
      {error && <div className="error" role="alert">{error}</div>}
      {cohorts.length > 1 && (
        <label className="field" style={{ maxWidth: 360 }}>Cohort
          <select value={detail?.id ?? ""} onChange={(e) => load(Number(e.target.value))}>
            {cohorts.map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
          </select>
        </label>
      )}
      {cohorts.length === 0 && !error && <section className="card"><p className="muted">You are not an instructor in any cohort.</p></section>}
      {detail && <SquadManager detail={detail} onChange={setDetail} onError={setError} />}
    </Shell>
  );
}
