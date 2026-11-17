"use client";

import { useEffect, useMemo, useState } from "react";
import { Shell } from "../../../components/Shell";
import { api } from "../../../lib/api";

export default function DocumentGovernance() {
  const [documents, setDocuments] = useState<any[]>([]);
  const [approvals, setApprovals] = useState<any[]>([]);
  const [message, setMessage] = useState("");
  const [left, setLeft] = useState<number>();
  const [right, setRight] = useState<number>();
  const [previews, setPreviews] = useState<any[]>([]);
  const [audience, setAudience] = useState("all");
  const [releaseDay, setReleaseDay] = useState("all");

  async function refresh() {
    const [documentRows, approvalRows] = await Promise.all([
      api<any[]>("/api/staff/curriculum-documents"),
      api<any[]>("/api/admin/approvals"),
    ]);
    setDocuments(documentRows);
    setApprovals(approvalRows.filter((item: any) => item.entity_type === "curriculum_document"));
  }

  useEffect(() => { refresh().catch((error) => setMessage(error.message)); }, []);

  const visibleDocuments = useMemo(() => documents.filter((document) =>
    (audience === "all" || document.audience === audience) &&
    (releaseDay === "all" || document.release_day === releaseDay)
  ), [documents, audience, releaseDay]);

  async function replace(document: any, file: File) {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(`/api/admin/curriculum-documents/${document.id}/replacement`, {
      method: "POST", credentials: "include", headers: { "X-PACT-Request": "1" }, body,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail ?? "Upload failed");
    setMessage(`Version ${result.version_number} is quarantined for asynchronous scanning.`);
    await refresh();
  }

  async function decide(id: number, decision: string) {
    try {
      await api(`/api/admin/approvals/${id}/decision`, { method: "POST", body: JSON.stringify({ decision, note: "Reviewed in document governance console" }) });
      await refresh();
    } catch (error) { setMessage((error as Error).message); }
  }

  async function retire(id: number) {
    try { await api(`/api/admin/curriculum-documents/${id}/retire`, { method: "POST" }); await refresh(); }
    catch (error) { setMessage((error as Error).message); }
  }

  async function compare() {
    try { setPreviews(await Promise.all([api(`/api/admin/curriculum-documents/${left}/preview`), api(`/api/admin/curriculum-documents/${right}/preview`)])); }
    catch (error) { setMessage((error as Error).message); }
  }

  return <Shell>
    <header className="page-header"><div><div className="eyebrow">Curriculum governance</div><h1>Controlled course documents</h1><p className="lede">Filter staged material, compare versions, approve clean documents, and retire obsolete content.</p></div></header>
    {message && <div className="notice" role="status">{message}</div>}
    <section className="card"><h2>Audience and release filters</h2><div className="row">
      <label>Audience<select value={audience} onChange={(event) => setAudience(event.target.value)}><option value="all">All audiences</option><option value="student">Student</option><option value="instructor">Instructor</option></select></label>
      <label>Release day<select value={releaseDay} onChange={(event) => setReleaseDay(event.target.value)}><option value="all">All release days</option>{["Mon", "Tue", "Wed", "Thu", "Fri"].map((day) => <option key={day}>{day}</option>)}</select></label>
      <span className="muted">{visibleDocuments.length} documents</span>
    </div></section>
    <section className="card"><h2>Version comparison</h2><div className="row">
      {[left, right].map((value, index) => <select aria-label={index === 0 ? "Left document version" : "Right document version"} key={index} value={value ?? ""} onChange={(event) => (index === 0 ? setLeft : setRight)(Number(event.target.value))}><option value="">Select version</option>{visibleDocuments.filter((document) => document.scan_status === "clean").map((document) => <option key={document.id} value={document.id}>{document.document_code} v{document.version_number}</option>)}</select>)}
      <button className="btn" disabled={!left || !right} onClick={compare}>Compare versions</button>
    </div>{previews.length === 2 && <div className="console-grid">{previews.map((preview) => <article className="card" key={preview.document_id}><h3>{preview.document_code} v{preview.version_number}</h3><p className="muted">{preview.slide_count} slides · {preview.byte_size.toLocaleString()} bytes · SHA-256 {preview.source_sha256.slice(0, 12)}…</p>{preview.slides.map((slide: any) => <details key={slide.number}><summary>Slide {slide.number}: {slide.title}</summary><pre>{slide.text}</pre></details>)}</article>)}</div>}</section>
    <section className="card table-card"><div className="table-wrap"><table><thead><tr><th>Document</th><th>Release</th><th>Version</th><th>Integrity</th><th>Approval</th><th>Replacement</th><th /></tr></thead><tbody>{visibleDocuments.map((document) => {
      const pending = approvals.find((approval) => approval.entity_code === `${document.document_code}/v${document.version_number}` && approval.status === "pending");
      return <tr key={document.id}><td><strong>{document.document_code} · {document.title}</strong><br /><span className="muted">{document.source_filename}</span></td><td>{document.audience ?? "Unassigned"}<br /><span className="muted">{document.release_day ? `${document.release_day} · ${document.release_block}` : "No release gate"}</span></td><td>v{document.version_number}{document.replaces_document_id ? ` replaces record ${document.replaces_document_id}` : " · original"}</td><td><span className={`status ${document.scan_status === "clean" ? "success" : ""}`}>{document.scan_status}</span><br /><span className="muted">{document.scan_engine ?? "—"}</span></td><td><span className="status">{document.approval_status}</span>{pending && <div className="row"><button className="btn" onClick={() => decide(pending.id, "approved")}>Approve</button><button className="btn secondary" onClick={() => decide(pending.id, "rejected")}>Reject</button></div>}</td><td><input aria-label={`Replacement for ${document.document_code} version ${document.version_number}`} type="file" accept=".pptx,.docx,.csv,.md,.txt" onChange={(event) => { const file = event.target.files?.[0]; if (file) replace(document, file).catch((error) => setMessage(error.message)); }} /></td><td><button className="text-button danger" disabled={document.approval_status === "retired"} onClick={() => retire(document.id)}>Retire</button></td></tr>;
    })}</tbody></table></div></section>
  </Shell>;
}
