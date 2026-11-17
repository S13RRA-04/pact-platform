"use client";

import { FormEvent, useEffect, useState } from "react";
import { Shell } from "../../components/Shell";
import { useRouter } from "next/navigation";
import { api, Me } from "../../lib/api";

export default function Account() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => { api<Me>("/api/me").then(setMe).catch(() => undefined); }, []);

  async function change(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    setError("");
    if (next !== confirm) {
      setError("The new passwords do not match.");
      return;
    }
    try {
      await api("/api/auth/password", { method: "POST", body: JSON.stringify({ current_password: current, new_password: next }) });
      setCurrent(""); setNext(""); setConfirm("");
      setMessage("Password changed. You were signed out everywhere else.");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Shell>
      <header className="page-header">
        <div>
          <div className="eyebrow">Your account</div>
          <h1>{me?.display_name ?? "Account"}</h1>
          <p className="lede">{me?.username}</p>
        </div>
        {/* Always reachable here: the sidebar sign-out control is hidden on narrow screens. */}
        <button className="btn secondary" onClick={async () => { await api("/api/auth/logout", { method: "POST" }); router.replace("/login"); }}>
          Sign out
        </button>
      </header>
      {message && <div className="notice" role="status">{message}</div>}
      {error && <div className="error" role="alert">{error}</div>}
      {me?.identity_provider === "dev-persona" ? (
        <section className="card"><p className="muted">Development personas have no password.</p></section>
      ) : (
        <section className="card" style={{ maxWidth: 480 }}>
          <h2>Change password</h2>
          <p className="muted">At least 12 characters. Lost your authenticator? Ask your program administrator for a reset link.</p>
          <form onSubmit={change}>
            <label className="field">Current password
              <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
            </label>
            <label className="field">New password
              <input type="password" autoComplete="new-password" minLength={12} maxLength={128} value={next} onChange={(e) => setNext(e.target.value)} required />
            </label>
            <label className="field">Confirm new password
              <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
            </label>
            <button className="btn" type="submit">Change password</button>
          </form>
        </section>
      )}
    </Shell>
  );
}
