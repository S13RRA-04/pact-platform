"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { downloadMaterial } from "../lib/materials";

type Deck = { id: number; document_code: string; title: string; approval_status: string; slide_count: number | null; slides: string[] };

/** The module's slide deck from the presentation suite. Staff see drafts (with an outline); students only
 * once the deck is approved. Lesson text itself is not generated here. */
export function ModuleDeck({ code }: { code: string }) {
  const [deck, setDeck] = useState<Deck | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setDeck(null);
    api<Deck | null>(`/api/curriculum/modules/${code}/presentation`).then(setDeck).catch(() => setDeck(null));
  }, [code]);

  if (!deck) return null;
  const draft = deck.approval_status !== "approved";
  return (
    <section className="card lesson-card" aria-label="Module slide deck">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <div className="eyebrow">Presentation deck · {deck.document_code}</div>
          <h2>{deck.title}</h2>
          <p className="muted">
            {deck.slide_count ? `${deck.slide_count} slides · ` : ""}Redesigned Presentation Suite v0.2
            {draft && " · Draft — not yet approved for delivery; visible to staff only"}
          </p>
        </div>
        <div className="actions">
          {draft && <span className="status warning">Draft</span>}
          {deck.slides.length > 0 && (
            <button className="btn secondary" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide outline" : "Slide outline"}</button>
          )}
          <button className="btn" onClick={() => downloadMaterial(deck.id).catch((e) => setError((e as Error).message))}>Download deck</button>
        </div>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {open && (
        <ol className="lesson-section">
          {deck.slides.map((title, i) => <li key={i}>{title}</li>)}
        </ol>
      )}
    </section>
  );
}
