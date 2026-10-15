import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Asterisk, ArrowRight, LoaderCircle, ShieldCheck } from "lucide-react";
import Portal from "./portal";
import "./styles.css";
const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");
function App() {
  const [user, setUser] = useState<{ displayName: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [register, setRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(BASE + "/api/session")
      .then(async (r) => {
        if (r.ok) setUser((await r.json()).user);
      })
      .catch(() => setError("The portal is temporarily unavailable."))
      .finally(() => setLoading(false));
  }, []);
  if (loading)
    return (
      <div className="loading">
        <LoaderCircle className="spin" />
        Opening your websites…
      </div>
    );
  if (user) return <Portal displayName={user.displayName} />;
  return (
    <div className="auth-page">
      <section className="auth-story">
        <a className="brand" href={BASE + "/"}>
          <Asterisk />
          <span>
            atelier<span className="brand-dot">.</span>
          </span>
        </a>
        <div>
          <div className="eyebrow">A LITTLE LESS ADMIN. A LOT MORE YOU.</div>
          <h1>
            Your next chapter.
            <br />
            <em>All in one place.</em>
          </h1>
          <p>
            A home for your website, your ideas
            <br />
            and everything that comes next.
          </p>
          <span className="auth-flower" aria-hidden="true">
            <Asterisk />
          </span>
        </div>
        <small>
          <ShieldCheck size={14} /> Espace privé · vos projets et conversations
        </small>
      </section>
      <section className="auth-form">
        <div className="eyebrow">MAKE YOURSELF AT HOME</div>
        <h2>{register ? "Your own little corner." : "Welcome back."}</h2>
        <p>
          {register
            ? "Create your account to start your first website conversation."
            : "Sign in to pick up where you left off."}
        </p>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            setBusy(true);
            setError("");
            const fields = new FormData(e.currentTarget);
            try {
              const r = await fetch(
                BASE + (register ? "/api/auth/register" : "/api/auth/login"),
                {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(Object.fromEntries(fields)),
                },
              );
              const data = await r.json();
              if (!r.ok) throw new Error(data.error);
              setUser(data.user);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {register && (
            <label>
              Your name
              <input
                name="displayName"
                autoComplete="name"
                minLength={2}
                maxLength={80}
                required
                placeholder="How should we call you?"
              />
            </label>
          )}
          <label>
            Username
            <input
              name="username"
              autoComplete="username"
              pattern="[a-zA-Z0-9._-]{3,40}"
              minLength={3}
              maxLength={40}
              required
              placeholder="Your username"
            />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete={register ? "new-password" : "current-password"}
              minLength={12}
              maxLength={128}
              required
              placeholder={
                register ? "At least 12 characters" : "Your password"
              }
            />
          </label>
          <button className="btn primary" disabled={busy}>
            {busy ? "One moment…" : register ? "Create my account" : "Sign in"}
            <ArrowRight size={16} />
          </button>
        </form>
        <button
          className="auth-switch"
          onClick={() => {
            setRegister(!register);
            setError("");
          }}
        >
          {register
            ? "Already have an account? Sign in"
            : "New here? Create an account"}
        </button>
        <p className="auth-note">
          Utilisez des données fictives pendant les essais. Aucun paiement ni
          publication commerciale automatique. Une maquette de test peut être construite sur votre demande explicite.
        </p>
      </section>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
