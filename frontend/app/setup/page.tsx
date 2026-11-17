"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";

type Setup = { username: string; display_name: string; purpose: string; totp_secret: string; otpauth_uri: string };

/** One-time account setup. The token arrives in the URL fragment (#token=…), which browsers never send to
 * the server or in Referer headers; it is removed from the address bar as soon as it is read. */
export default function AccountSetup() {
  const [token, setToken] = useState("");
  const [setup, setSetup] = useState<Setup | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // StrictMode runs effects twice in development
    started.current = true;
    const raw = new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "";
    window.history.replaceState(null, "", window.location.pathname);
    if (!raw) {
      setError("This page needs the one-time setup link from your administrator.");
      return;
    }
    setToken(raw);
    api<Setup>("/api/auth/setup/start", { method: "POST", body: JSON.stringify({ token: raw }) })
      .then(setSetup)
      .catch((e) => setError((e as Error).message));
  }, []);

  async function complete(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError("The passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api("/api/auth/setup/complete", {
        method: "POST",
        body: JSON.stringify({ token, password, totp_code: code }),
      });
      setDone(true);
      setPassword("");
      setConfirm("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <section className="login-intro">
        <div className="login-wordmark">
          <div className="brand-mark">P</div>
          <div><div className="brand-name">PACT</div><small>Learning & Case Simulation Platform</small></div>
        </div>
        <div className="login-copy">
          <div className="eyebrow" style={{ color: "#6fd1df" }}>Account setup</div>
          <h1>Two factors protect every account.</h1>
          <p>You will set a password and link an authenticator app. Both are required each time you sign in.</p>
        </div>
        <div className="login-disclaimer">Synthetic training data only · Not authorized for operational use</div>
      </section>

      <section className="login">
        {done ? (
          <>
            <div className="eyebrow">Complete</div>
            <h1>Your account is ready</h1>
            <p className="lede">Sign in with your username, your new password and a code from your authenticator app.</p>
            <Link className="btn" href="/login">Go to sign in</Link>
          </>
        ) : (
          <>
            <div className="eyebrow">{setup?.purpose === "reset" ? "Reset credentials" : "First-time setup"}</div>
            <h1>{setup ? `Welcome, ${setup.display_name}` : "Set up your account"}</h1>
            {error && <div className="error" role="alert" style={{ marginTop: 18 }}>{error}</div>}
            {setup && (
              <form className="login-form" onSubmit={complete}>
                <p className="lede">Username: <strong>{setup.username}</strong></p>
                <h2>1. Add PACT to your authenticator app</h2>
                <p className="muted">
                  In your authenticator app, choose to add an account by entering a setup key, then enter this key
                  (time-based, 6 digits). On a device with an authenticator installed you can also{" "}
                  <a href={setup.otpauth_uri}>open it directly</a>.
                </p>
                <div className="secret-box" aria-label="Authenticator setup key">
                  {setup.totp_secret.match(/.{1,4}/g)?.join(" ")}
                </div>
                <h2>2. Choose a password</h2>
                <p className="muted">At least 12 characters. A passphrase of several words works well. Do not include your username.</p>
                <label className="field">New password
                  <input type="password" autoComplete="new-password" value={password}
                    onChange={(e) => setPassword(e.target.value)} minLength={12} maxLength={128} required />
                </label>
                <label className="field">Confirm password
                  <input type="password" autoComplete="new-password" value={confirm}
                    onChange={(e) => setConfirm(e.target.value)} required />
                </label>
                <h2>3. Confirm your authenticator</h2>
                <label className="field">Current 6-digit code
                  <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required />
                </label>
                <button className="btn" type="submit" disabled={busy || code.length !== 6}>
                  {busy ? "Saving…" : "Activate account"}
                </button>
              </form>
            )}
          </>
        )}
      </section>
    </div>
  );
}
