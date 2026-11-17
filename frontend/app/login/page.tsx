"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "../../lib/api";

type Persona = { username: string; display_name: string; persona_label: string };

export default function Login() {
  const router = useRouter();
  const [step, setStep] = useState<"password" | "mfa">("password");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Personas are listed only when the backend exposes the development-only endpoint (never in production).
  const [personas, setPersonas] = useState<Persona[]>([]);

  useEffect(() => {
    api<Persona[]>("/api/dev/personas").then(setPersonas).catch(() => setPersonas([]));
  }, []);

  async function submitPassword(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
      setPassword("");
      setStep("mfa");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/auth/mfa", { method: "POST", body: JSON.stringify({ code }) });
      router.push("/dashboard");
    } catch (e) {
      setCode("");
      setError((e as Error).message);
      if ((e as Error).message.includes("expired")) setStep("password");
    } finally {
      setBusy(false);
    }
  }

  async function choosePersona(name: string) {
    try {
      await api("/api/dev/login", { method: "POST", body: JSON.stringify({ username: name }) });
      router.push("/dashboard");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="login-shell">
      <section className="login-intro">
        <div className="login-wordmark">
          <div className="brand-mark">P</div>
          <div>
            <div className="brand-name">PACT</div>
            <small>Learning & Case Simulation Platform</small>
          </div>
        </div>
        <div className="login-copy">
          <div className="eyebrow" style={{ color: "#6fd1df" }}>Professional cyber investigation training</div>
          <h1>Build judgment through realistic casework.</h1>
          <p>Structured instruction, synthetic evidence, pathway-specific assignments, and individual competency review in one secure training workspace.</p>
        </div>
        <div className="login-disclaimer">Synthetic training data only · Not authorized for operational use</div>
      </section>

      <section className="login">
        <div className="eyebrow">Secure sign-in</div>
        <h1>{step === "password" ? "Sign in to PACT" : "Enter your authenticator code"}</h1>
        <p className="lede">
          {step === "password"
            ? "Use the account your program administrator set up for you."
            : "Open your authenticator app and enter the current 6-digit code for PACT Training."}
        </p>
        {error && <div className="error" role="alert" style={{ marginTop: 18 }}>{error}</div>}

        {step === "password" ? (
          <form className="login-form" onSubmit={submitPassword}>
            <label className="field">Username
              <input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
            </label>
            <label className="field">Password
              <input type="password" autoComplete="current-password" value={password}
                onChange={(e) => setPassword(e.target.value)} required />
            </label>
            <button className="btn" type="submit" disabled={busy}>{busy ? "Checking…" : "Continue"}</button>
          </form>
        ) : (
          <form className="login-form" onSubmit={submitCode}>
            <label className="field">Authenticator code
              <input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required autoFocus />
            </label>
            <div className="row">
              <button className="btn" type="submit" disabled={busy || code.length !== 6}>{busy ? "Verifying…" : "Sign in"}</button>
              <button className="btn secondary" type="button" onClick={() => { setStep("password"); setCode(""); setError(""); }}>Back</button>
            </div>
          </form>
        )}
        <p className="muted" style={{ marginTop: 18 }}>Locked out or lost your authenticator? Contact your program administrator for a reset link.</p>

        {personas.length > 0 && (
          <div className="login-divider">
            <div className="eyebrow">Local development access</div>
            <p className="lede">Synthetic personas. This list is disabled outside development.</p>
            <div className="persona-grid">
              {personas.map((p) => (
                <button className="card persona" key={p.username} onClick={() => choosePersona(p.username)}>
                  <h2>{p.display_name}</h2>
                  <span className="status">{p.persona_label}</span>
                  <p className="muted">{p.username}</p>
                  <span className="persona-arrow">→</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
