"use client";

import { useEffect, useState } from "react";
import { Shell } from "../../components/Shell";
import { api } from "../../lib/api";

type Challenge = {
  code: string; item_type: string; title: string; body: string; time_limit_minutes: number | null;
  instrument_code: string | null; scored: boolean; released_at: string | null;
};

export default function Challenges() {
  const [items, setItems] = useState<Challenge[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Challenge[]>("/api/student/challenges")
      .then(setItems)
      .catch(() => setError("Challenges are released to enrolled students during the course."));
  }, []);

  return (
    <Shell>
      <header className="page-header">
        <div>
          <div className="eyebrow">Student workspace</div>
          <h1>Challenges and debriefs</h1>
          <p className="lede">Timed tasks and debriefs your instructor has released to your cohort. New items also appear in Notifications.</p>
        </div>
      </header>
      {error && <div className="notice" role="status">{error}</div>}
      {items && items.length === 0 && <section className="card empty-state"><p className="muted">Nothing has been released yet. Your instructor releases challenges as the exercise progresses.</p></section>}
      {items?.map((c) => (
        <section className="card" key={c.code}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div>
              <div className="eyebrow">{c.item_type === "debrief" ? "Debrief" : "Challenge"} · {c.code}</div>
              <h2>{c.title}</h2>
            </div>
            <div className="actions">
              {c.time_limit_minutes && <span className="status warning">{c.time_limit_minutes} minutes</span>}
              <span className={`status ${c.scored ? "danger" : "neutral"}`}>{c.scored ? `Scored · ${c.instrument_code}` : "Practice · not scored"}</span>
            </div>
          </div>
          <p style={{ whiteSpace: "pre-wrap" }}>{c.body}</p>
          {c.released_at && <p className="muted">Released {new Date(c.released_at).toLocaleString()}</p>}
        </section>
      ))}
    </Shell>
  );
}
