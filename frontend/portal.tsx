"use client";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Asterisk,
  Check,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Clock3,
  CreditCard,
  ExternalLink,
  FileText,
  Globe,
  LayoutDashboard,
  Leaf,
  LoaderCircle,
  Menu,
  MessageCircle,
  Monitor,
  Plus,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sprout,
  X,
} from "lucide-react";
import type { Brief, Project } from "../lib/contracts";
import { formatMoney } from "../lib/format";
const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");
function Concept({
  project,
  large = false,
}: {
  project?: Project;
  large?: boolean;
}) {
  const brief = project?.brief;
  const bold = brief?.style === "Bold & expressive";
  const clean = brief?.style === "Clean & modern";
  return (
    <div
      className={`concept ${large ? "large" : ""} ${bold ? "bold" : clean ? "clean" : ""}`}
    >
      <div className="concept-nav">
        <span>
          <Sprout size={14} /> {brief?.businessName || "your business"}
        </span>
        <div>
          {(brief?.pages || ["Home", "About", "Services"])
            .slice(0, 4)
            .map((page) => (
              <span key={page}>{page}</span>
            ))}
        </div>
      </div>
      <div className="concept-body">
        <div className="concept-copy">
          <small>{brief?.industry || "SOMETHING GOOD IS GROWING"}</small>
          <h3>
            {project?.sample ? (
              <>
                Flowers for
                <br />
                the everyday
                <br />
                <em>and the extraordinary.</em>
              </>
            ) : (
              <>
                A little more
                <br />
                <em>{brief?.businessName || "you, online."}</em>
              </>
            )}
          </h3>
          <p>
            {brief?.description ||
              "A thoughtful space for your business to bloom. Made for you, with room to grow."}
          </p>
          <span className="concept-cta">
            Discover our story <ArrowUpRight size={11} />
          </span>
        </div>
        <div className="botanical" aria-hidden="true">
          <div className="paper-circle" />
          <div className="stem s1">
            <i />
            <i />
            <i />
          </div>
          <div className="stem s2">
            <i />
            <i />
            <i />
          </div>
          <div className="stem s3">
            <i />
            <i />
          </div>
          <div className="flower f1">
            <b />
            <b />
            <b />
            <b />
            <b />
            <b />
            <b />
            <b />
            <span />
          </div>
          <div className="flower f2">
            <b />
            <b />
            <b />
            <b />
            <b />
            <b />
            <b />
            <b />
            <span />
          </div>
          <div className="vase" />
        </div>
      </div>
      <div className="concept-foot">
        <span>Thoughtfully made. Naturally yours.</span>
        <span>EST. 2026</span>
      </div>
    </div>
  );
}

type View = "Overview" | "Assistant" | "Plan & billing" | "Settings";
type Modal = "new" | "preview" | "brief" | "help" | "support" | null;
type SupportTicket = { id: string; status: "queued" | "running" | "sent" | "unknown"; created: number };
function SupportForm({ project, refresh }: { project: Project; refresh: () => Promise<void> }) {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [consent, setConsent] = useState(false);
  const [available, setAvailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [submitted, setSubmitted] = useState(false);
  const attempt = useRef<{ requestId: string; revision: number; email: string; message: string; consent: true } | null>(null);
  useEffect(() => { setConsent(false); }, [project.revision]);
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await fetch(`${BASE}/api/projects/${project.id}/support`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Suivi indisponible.");
        if (active) { setAvailable(data.available); setTickets(data.tickets); setLoading(false); }
      } catch (e) { if (active) { setError((e as Error).message); setLoading(false); } }
    }
    void load();
    const timer = window.setInterval(() => { void load(); }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [project.id]);
  const inProgress = tickets.some(t => t.status === "queued" || t.status === "running");
  async function send(e: FormEvent) {
    e.preventDefault();
    if (sending || submitted) return;
    const body = attempt.current || { requestId: crypto.randomUUID(), revision: project.revision, email, message, consent: true as const };
    attempt.current = body;
    setSending(true); setError("");
    try {
      const response = await fetch(`${BASE}/api/projects/${project.id}/support`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok) {
        if (response.status < 500) attempt.current = null;
        if (response.status === 409) { setConsent(false); await refresh(); }
        throw new Error(data.error || "Envoi non confirmé. Vérifiez le suivi avant de réessayer.");
      }
      setTickets(prev => [data.ticket, ...prev.filter(t => t.id !== data.ticket.id)]);
      setSubmitted(true);
    } catch (e) { setError((e as Error).message); }
    finally { setSending(false); }
  }
  return <>
    <div className="eyebrow">UNE PERSONNE POUR VOUS AIDER</div>
    <h2>Contacter le <em>support.</em></h2>
    <p className="modal-intro">Pour le site « {project.name} ». Expliquez le problème ; nous transmettrons son contexte au support.</p>
    <div className="support-context">
      <strong>Ce qui sera joint</strong>
      <p>La conversation conservée ({project.messages.length} messages, 100 au maximum), le brief et l’état de génération.</p>
      <p>{project.preview?.generated ? `Le lien privé et une copie HTML de la dernière maquette générée, version ${project.preview.version}.` : "Si une maquette générée est enregistrée, son lien et sa copie HTML seront joints ; sinon le support sera informé de son absence."}</p>
      <small>Le lien conserve les accès privés du portail. La copie jointe permet au support d’examiner la maquette.</small>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    {loading ? <p role="status">Chargement du support…</p> : !available ? <p role="status">Le formulaire de support n’est pas encore disponible.</p> : !submitted && <form onSubmit={e => void send(e)}>
      <fieldset disabled={sending || !!attempt.current}>
        <label>Votre adresse e-mail pour la réponse<input type="email" autoComplete="email" required maxLength={254} value={email} onChange={e => setEmail(e.target.value)} /></label>
        <label>Que s’est-il passé ?<textarea required minLength={10} maxLength={4000} rows={4} value={message} onChange={e => setMessage(e.target.value)} placeholder="Décrivez le problème et ce que vous attendiez…" /></label>
        <label className="checkbox-label"><input type="checkbox" checked={consent} required onChange={e => setConsent(e.target.checked)} />J’accepte d’envoyer au support cette conversation, le brief et la maquette disponible.</label>
      </fieldset>
      <button className="btn primary" disabled={sending || (!attempt.current && (!consent || inProgress || message.trim().length < 10))}>
        {sending ? "Enregistrement…" : attempt.current ? "Vérifier le même envoi" : "Envoyer au support"}<Send size={15} />
      </button>
    </form>}
    {!!tickets.length && <div className="support-history" aria-live="polite">
      <h3>Suivi des demandes</h3>
      {tickets.map(ticket => <div key={ticket.id}>
        <p><strong>{ticket.status === "sent" ? "E-mail envoyé" : ticket.status === "unknown" ? "Envoi non confirmé" : "Demande enregistrée — envoi en cours"}</strong></p>
        <small>Référence : {ticket.id}</small>
        {ticket.status === "sent" && <p>Le service de messagerie a confirmé l’envoi. Cela ne garantit pas la lecture par le support.</p>}
        {ticket.status === "unknown" && <p>Le mail a peut-être été envoyé. Aucun renvoi automatique n’a lieu ; conservez cette référence avant toute nouvelle demande.</p>}
      </div>)}
    </div>}
  </>;
}
type Category = "small_edit" | "extra_page" | "redesign" | "advanced";
type Route = { view: View; projectId?: string };
type Draft = { text: string; category: Category | "" };
const services: { value: Category | ""; label: string; detail: string }[] = [
  {
    value: "",
    label: "Let’s talk",
    detail:
      "Ask questions and shape your idea before deciding. No payment required to chat.",
  },
  {
    value: "extra_page",
    label: "Add a page · €99",
    detail:
      "Describe one standard page. A draft quote will appear in this conversation for you to review.",
  },
  {
    value: "small_edit",
    label: "Content edit",
    detail:
      "Describe the content change. Eligibility and scope need review; your care plan has not started.",
  },
  {
    value: "redesign",
    label: "Design refresh",
    detail:
      "From €149, subject to a final scope review and custom quote. Nothing starts automatically.",
  },
  {
    value: "advanced",
    label: "Advanced feature",
    detail:
      "Describe the outcome. Advanced work requires a separate scope review and quote.",
  },
];
const labels: Record<string, string> = {
  brief_ready: "In preparation",
  awaiting_payment: "Payment pending",
  quoted: "Quote ready",
  needs_scope_review: "Scope review needed",
  accepted_pending_payment: "Payment pending",
  cancelled: "Cancelled",
  awaiting_review: "Ready for review",
  approved_pending_connection: "Approval recorded",
  changes_requested: "Changes requested",
};
const EMPTY_BRIEF: Brief = {
  businessName: "",
  industry: "",
  description: "",
  audience: "",
  pages: ["Home", "About", "Services", "Contact"],
  style: "Warm & natural",
  website: "",
};
function routeFromHash(): Route {
  const hash = window.location.hash;
  const site = /^#\/sites\/([0-9a-f-]{36})$/.exec(hash);
  if (site) return { view: "Assistant", projectId: site[1] };
  if (hash === "#/billing") return { view: "Plan & billing" };
  if (hash === "#/settings") return { view: "Settings" };
  return { view: "Overview" };
}
function Badge({
  children,
  tone = "sage",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export default function Portal({ displayName }: { displayName: string }) {
  const [route, setRoute] = useState<Route>(routeFromHash);
  const view = route.view;
  const [modal, setModal] = useState<Modal>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);
  const [pipelineConfig, setPipelineConfig] = useState({ available: false, driveAccount: "" });
  const [sourceDrafts, setSourceDrafts] = useState<Record<string, { url: string; consent: boolean }>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [brief, setBrief] = useState<Brief>(EMPTY_BRIEF);
  const [step, setStep] = useState(1);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [feedback, setFeedback] = useState("");
  const [approvedPreviewKey, setApprovedPreviewKey] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const endOfChat = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const p = projects.find((project) => project.id === route.projectId);
  const previewKey = p?.preview ? `${p.id}:${p.preview.version}:${p.preview.sha256 || "template"}` : "";
  const confirmApproval = Boolean(previewKey) && approvedPreviewKey === previewKey;
  const previewFailure = p?.integration?.kind === "generate_preview" && ["failed", "unknown", "stale"].includes(p.integration.status);
  const draft = drafts[route.projectId || ""] || { text: "", category: "" };
  useEffect(() => {
    void refresh();
    void fetch(`${BASE}/api/health`).then(r => r.json()).then(h => setConnected(h.mode === "n8n_test_frontend")).catch(() => {});
    void fetch(`${BASE}/api/pipeline`).then(r => r.ok ? r.json() : Promise.reject()).then(h => setPipelineConfig({ available: h.available === true, driveAccount: typeof h.driveAccount === "string" ? h.driveAccount : "" })).catch(() => {});
  }, []);
  const pending = ["queued", "running", "building"].includes(p?.integration?.status || "");
  useEffect(() => {
    if (!projects.some(item => ["queued", "running", "building"].includes(item.integration?.status || "") || item.pipeline?.state === "REVIEW_REQUIRED")) return;
    const timer = window.setInterval(() => { if (!busy) void refresh(); }, 2000);
    return () => window.clearInterval(timer);
  }, [projects, busy]);
  useEffect(() => {
    const update = () => {
      setRoute(routeFromHash());
      setModal(null);
      setMobileNav(false);
      setError("");
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  useEffect(() => {
    if (modal) dialog.current?.showModal();
    else dialog.current?.close();
  }, [modal]);
  useEffect(() => {
    const messages = endOfChat.current?.parentElement;
    if (view === "Assistant" && messages)
      messages.scrollTo({ top: messages.scrollHeight, behavior: "smooth" });
  }, [p?.id, p?.revision, view]);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 5500);
    return () => clearTimeout(t);
  }, [notice]);
  function navigate(next: View, projectId?: string) {
    window.location.hash =
      next === "Assistant" && projectId
        ? `/sites/${projectId}`
        : next === "Plan & billing"
          ? "/billing"
          : next === "Settings"
            ? "/settings"
            : "/overview";
  }
  async function refresh() {
    try {
      const r = await fetch(`${BASE}/api/projects`);
      const data = (await r.json()) as { projects: Project[]; error?: string };
      if (!r.ok) throw new Error(data.error);
      setProjects(data.projects);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not load your websites.",
      );
    } finally {
      setLoading(false);
    }
  }
  async function api(path: string, method: string, data: unknown) {
    const r = await fetch(BASE + path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const body = (await r.json()) as { project: Project; error?: string };
    if (!r.ok) {
      if (r.status === 409) await refresh();
      throw new Error(body.error || "Could not save your changes.");
    }
    return body;
  }
  async function create(sample = false) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const data = await api(
        "/api/projects",
        "POST",
        sample ? { sample: true } : { brief },
      );
      setProjects((prev) => [data.project, ...prev]);
      setModal(null);
      navigate("Assistant", data.project.id);
      setNotice(
        sample
          ? "Your fictional website conversation is ready."
          : "Your website is ready to talk about.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function act(action: unknown, success?: string) {
    if (!p || busy || pending) return false;
    const target = p;
    setBusy(true);
    setError("");
    try {
      const data = await api(`/api/projects/${target.id}`, "PATCH", {
        revision: target.revision,
        action,
      });
      setProjects((prev) =>
        prev.map((item) => (item.id === target.id ? data.project : item)),
      );
      if (success) setNotice(success);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }
  function changeDraft(change: Partial<Draft>) {
    if (p)
      setDrafts((prev) => ({
        ...prev,
        [p.id]: { ...(prev[p.id] || { text: "", category: "" }), ...change },
      }));
  }
  async function sendMessage(e: FormEvent) {
    e.preventDefault();
    if (!p) return;
    const siteId = p.id;
    const action = {
      type: "message",
      text: draft.text,
      ...(draft.category ? { serviceCategory: draft.category } : {}),
    };
    if (await act(action))
      setDrafts((prev) => ({ ...prev, [siteId]: { text: "", category: "" } }));
  }
  function open(m: Modal) {
    setError("");
    setApprovedPreviewKey("");
    setFeedback("");
    setModal(m);
  }
  function start() {
    setBrief(EMPTY_BRIEF);
    setStep(1);
    open("new");
  }
  async function signOut(e: React.MouseEvent<HTMLAnchorElement>) {
    e.preventDefault();
    try {
      await api("/api/auth/logout", "POST", {});
      window.location.assign(BASE + "/");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function exportProject(project: Project) {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(project, null, 2)], {
        type: "application/json",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `atelier-${project.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
    setNotice("Your website export is ready.");
  }
  const button = (
    label: string,
    onClick: () => void,
    kind = "primary",
    icon: ReactNode = <ArrowRight size={15} />,
  ) => (
    <button className={`btn ${kind}`} onClick={onClick} disabled={busy}>
      {label}
      {icon}
    </button>
  );
  const requestCard = (request: Project["requests"][number]) => (
    <div className="chat-offer" key={request.id}>
      <div className="offer-top">
        <span>
          <FileText size={15} />
          {request.title}
        </span>
        <Badge tone={request.status === "cancelled" ? "neutral" : "sage"}>
          {labels[request.status]}
        </Badge>
      </div>
      <p>{request.description}</p>
      <div className="offer-price">
        {formatMoney(request.cents)}
        <small>
          {request.cents === null
            ? "Final scope and price need review"
            : "Draft fixed price · no payment collected"}
        </small>
      </div>
      {request.assetUrl && (
        <a
          className="text-link"
          href={request.assetUrl}
          target="_blank"
          rel="noreferrer"
        >
          Reference <ExternalLink size={12} />
        </a>
      )}
      <div className="offer-actions">
        {request.status === "quoted" && (
          <button
            className="btn secondary"
            disabled={busy}
            onClick={() =>
              void act(
                { type: "accept_request", requestId: request.id },
                "Quote acceptance saved. No payment collected.",
              )
            }
          >
            Accept draft quote · {formatMoney(request.cents)}{" "}
            <ArrowRight size={13} />
          </button>
        )}
        {request.status !== "cancelled" && (
          <button
            className="cancel-offer"
            disabled={busy}
            onClick={() =>
              void act(
                { type: "cancel_request", requestId: request.id },
                "Change cancelled.",
              )
            }
          >
            Cancel this change
          </button>
        )}
      </div>
    </div>
  );
  const creationQuote = p && (
    <div className="chat-offer creation-offer">
      <div className="offer-top">
        <span>
          <Sprout size={17} />
          Your website, when you’re ready.
        </span>
        <Badge tone="neutral">Draft offer</Badge>
      </div>
      <div className="offer-price">
        {formatMoney(p.initialQuote.cents)}
        <small>Creation · one time</small>
      </div>
      <p>
        Proposed hosting and care: {formatMoney(p.initialQuote.monthlyCents)}
        /month after launch. Talk through your idea first; chatting does not
        require payment.
      </p>
      {p.initialQuote.status === "draft" ? (
        <button
          className="btn secondary"
          disabled={busy}
          onClick={() =>
            void act(
              { type: "accept_initial_quote" },
              "Intent saved. You have not been charged.",
            )
          }
        >
          Accept draft creation quote <ArrowRight size={13} />
        </button>
      ) : (
        <Badge>Acceptance recorded · payment pending</Badge>
      )}
      <small className="offer-footnote">
        Final scope, terms and tax treatment must be confirmed before checkout.
        Payments are not connected.
      </small>
    </div>
  );

  return (
    <div className="app-shell">
      {mobileNav && (
        <button
          className="nav-overlay"
          aria-label="Close navigation"
          onClick={() => setMobileNav(false)}
        />
      )}
      <aside className={`sidebar ${mobileNav ? "open" : ""}`}>
        <a
          className="brand"
          href={BASE + "/#/overview"}
          aria-label="Atelier home"
        >
          <Asterisk strokeWidth={2.5} />
          <span>
            atelier<span className="brand-dot">.</span>
          </span>
        </a>
        <div className="sites-navigation-label">MADE FOR YOUR NEXT CHAPTER</div>
        <nav aria-label="Main navigation">
          <button
            className={
              view === "Overview" || view === "Assistant" ? "active" : ""
            }
            onClick={() => navigate("Overview")}
          >
            <LayoutDashboard size={18} />
            Overview<span className="nav-count">{projects.length}</span>
          </button>
          <button
            className={view === "Plan & billing" ? "active" : ""}
            onClick={() => navigate("Plan & billing")}
          >
            <CreditCard size={18} />
            Plan & billing
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="plan-teaser">
            <Sparkles size={18} />
            <h4>
              One site.
              <br />
              One conversation.
            </h4>
            <p>
              Pick a website. Share your ideas.
              <br />
              We’ll keep its story together.
            </p>
            <button onClick={start} disabled={busy}>
              Start another website <Plus size={14} />
            </button>
          </div>
          <button
            className={`side-link ${view === "Settings" ? "active" : ""}`}
            onClick={() => navigate("Settings")}
          >
            <Settings2 size={17} />
            Settings
          </button>
          <button className="side-link" onClick={() => open("help")}>
            <CircleHelp size={17} />
            Help & getting started
          </button>
          {p && <button className="side-link" onClick={() => open("support")}><MessageCircle size={17} />Contacter le support</button>}
          <div className="account">
            <span>{displayName.charAt(0).toUpperCase()}</span>
            <div>
              <strong>
                {displayName.includes("@")
                  ? displayName.split("@")[0]
                  : displayName}
              </strong>
              <small>Your account</small>
            </div>
            <a href={BASE + "/logout"} onClick={signOut} aria-label="Sign out">
              <ExternalLink size={15} />
            </a>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu icon-btn"
              onClick={() => setMobileNav(true)}
              aria-label="Open navigation"
            >
              <Menu size={20} />
            </button>
            <button onClick={() => navigate("Overview")}>Your websites</button>
            <ChevronRight size={13} />
            <strong>
              {view === "Assistant" ? p?.name || "Assistant" : view}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="private-label">
              <ShieldCheck size={14} />
              Private preview
            </span>
            <span className="avatar">
              {displayName.charAt(0).toUpperCase()}
            </span>
          </div>
        </header>
        <main
          className={view === "Assistant" ? "assistant-page" : "portfolio-page"}
        >
          {view !== "Assistant" && (
            <div className="page-heading">
              <div>
                <div className="eyebrow">YOUR WEBSITES, WITH ROOM TO GROW</div>
                <h1>
                  {view === "Overview" ? (
                    <>
                      Every website.
                      <br className="mobile-title-break" />
                      <em> Its own conversation.</em>
                    </>
                  ) : view === "Plan & billing" ? (
                    <>
                      Simple plans.<em> Clear possibilities.</em>
                    </>
                  ) : (
                    <>
                      Make yourself<em> at home.</em>
                    </>
                  )}
                </h1>
                <p>
                  {view === "Overview"
                    ? "From your first idea to the next little change. Choose a site to pick up the conversation."
                    : view === "Plan & billing"
                      ? "See the offer. Ask questions. Decide when you’re ready."
                      : "Your account and the information that belongs to you."}
                </p>
              </div>
              {button("New website", start, "primary", <Plus size={16} />)}
            </div>
          )}
          {view !== "Assistant" && (
            <div className="sandbox-strip">
              <span>
                <span className="status-dot" />
                PORTAL PREVIEW
              </span>
              <p>
                {connected ? "Discutez de votre projet et préparez une maquette de test avant de vous engager. Aucun paiement ni publication automatique." : "Explore ideas before paying. This portal uses demonstration replies."}
              </p>
              <button onClick={() => open("help")}>
                What’s included <ArrowUpRight size={13} />
              </button>
            </div>
          )}
          {error && (
            <div className="error" role="alert">
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={15} />
              </button>
            </div>
          )}
          {loading ? (
            <div className="loading">
              <LoaderCircle className="spin" />
              Getting your websites ready…
            </div>
          ) : (
            <>
              {view === "Overview" && (
                <>
                  <div className="portfolio-heading">
                    <div>
                      <h2>
                        Your websites <span>{projects.length}</span>
                      </h2>
                      <p>
                        Each site keeps its own brief, messages, quotes and
                        approvals.
                      </p>
                    </div>
                    {projects.length > 0 && (
                      <span className="hosting-note">
                        <ShieldCheck size={14} />
                        Hosting has not started
                      </span>
                    )}
                  </div>
                  {projects.length ? (
                    <div className="website-feed">
                      {projects.map((project) => (
                        <a
                          className="site-tile"
                          href={`#/sites/${project.id}`}
                          key={project.id}
                          aria-label={`Open assistant for ${project.name}`}
                        >
                          <div className="site-thumbnail">
                            <div className="site-browser-top">
                              <div className="browser-dots">
                                <i />
                                <i />
                                <i />
                              </div>
                              <span>
                                {project.sample
                                  ? "Fictional sample"
                                  : "Private concept"}
                              </span>
                            </div>
                            <Concept project={project} />
                          </div>
                          <div className="site-tile-info">
                            <div>
                              <h3>{project.name}</h3>
                              <Badge tone={project.sample ? "neutral" : "sage"}>
                                {project.sample
                                  ? "Sample"
                                  : labels[project.status] || "In preparation"}
                              </Badge>
                            </div>
                            <p>{project.brief.industry}</p>
                            <div className="site-conversation-meta">
                              <span>
                                <MessageCircle size={12} />
                                {
                                  project.messages.filter(
                                    (m) => m.role === "user",
                                  ).length
                                }{" "}
                                saved messages
                              </span>
                              <span>
                                {new Date(project.updatedAt).toLocaleDateString(
                                  "en-GB",
                                  { day: "numeric", month: "short" },
                                )}
                              </span>
                            </div>
                            <div className="site-tile-footer">
                              <span>Open website assistant</span>
                              <ArrowUpRight size={17} />
                            </div>
                          </div>
                        </a>
                      ))}
                    </div>
                  ) : (
                    <section className="portfolio-empty">
                      <div className="empty-copy">
                        <div className="eyebrow">
                          SOMETHING GOOD STARTS WITH AN IDEA
                        </div>
                        <h2>
                          Your first website.
                          <br />
                          <em>Your first conversation.</em>
                        </h2>
                        <p>
                          Tell us about your business, then chat through the
                          possibilities. You can ask questions before accepting
                          a quote.
                        </p>
                        <div className="empty-actions">
                          {button(
                            "Start your website",
                            start,
                            "primary",
                            <Plus size={16} />,
                          )}
                          {button(
                            "Explore a fictional sample",
                            () => void create(true),
                            "secondary",
                            <ArrowUpRight size={15} />,
                          )}
                        </div>
                        <small>
                          No payment or subscription starts when you create a
                          brief.
                        </small>
                      </div>
                      <div className="empty-concept">
                        <Concept />
                      </div>
                    </section>
                  )}
                  <div className="portfolio-bottom-note">
                    <Asterisk size={20} />
                    <div>
                      <strong>
                        A little less admin. A little more conversation.
                      </strong>
                      <p>
                        Choose a website above to talk about its next chapter.
                        Everything for that site stays in the same chat.
                      </p>
                    </div>
                  </div>
                </>
              )}

              {view === "Assistant" &&
                (p ? (
                  <>
                    <div className="site-chat-title">
                      <button
                        className="text-link"
                        onClick={() => navigate("Overview")}
                      >
                        <ArrowLeft size={14} />
                        All websites
                      </button>
                      <div className="site-chat-heading">
                        <div>
                          <div className="eyebrow">YOUR WEBSITE ASSISTANT</div>
                          <h1>{p.name}</h1>
                          <p>
                            {p.brief.industry}
                            {p.sample
                              ? " · Fictional sample"
                              : " · In preparation"}
                          </p>
                        </div>
                        <div className="site-chat-tools">
                          {button(
                            "View brief",
                            () => open("brief"),
                            "secondary",
                            <FileText size={15} />,
                          )}
                          {button(
                            pending ? "Préparation en cours…" : p.preview ? "Voir la maquette" : connected ? "Générer une maquette" : "Explore a concept",
                            async () => {
                          if (pipelineConfig.available && !p.preview) {
                            setNotice("Relisez le brief vérifié dans Documents et images, puis confirmez sa construction.");
                            document.getElementById("project-source-review")?.scrollIntoView({ behavior: "smooth", block: "center" });
                            return;
                          }
                          const ready =
                            p.preview ||
                            (await act({ type: "generate_preview" }));
                          if (ready && routeFromHash().projectId === p.id)
                                open("preview");
                            },
                            "secondary",
                            <Monitor size={15} />,
                          )}
                        </div>
                      </div>
                    </div>
                    {pipelineConfig.available && <section id="project-source-review" className="card source-panel" aria-label="Documents et suivi du projet">
                      <h2>Documents et images du projet</h2>
                      <p>Partagez votre dossier Google Drive en privé avec <strong>{pipelineConfig.driveAccount || "le compte de lecture communiqué par le support"}</strong>, avec le rôle Lecteur. Ajoutez votre cahier des charges, vos images et les données de vos produits. Les fichiers sont lus comme des sources du brief.</p>
                      <p>Vous pouvez aussi fournir le lien directement dans votre message : son envoi autorise la lecture de ce dossier pour ce site. Les liens cités ou transférés ne sont pas importés automatiquement.</p>
                      <p>Le lecteur accepte PDF texte, Google Docs, TXT et CSV. Les PNG peuvent être utilisés dans la maquette. Les autres images et les formats non pris en charge demandent une vérification ; un document incomplet bloque la construction.</p>
                      <form onSubmit={async e => {
                        e.preventDefault();
                        const source = sourceDrafts[p.id];
                        if (source && await act({ type: "set_sources", folderUrl: source.url, consent: source.consent }))
                          setSourceDrafts(prev => ({ ...prev, [p.id]: { url: "", consent: false } }));
                      }}>
                        <label htmlFor="drive-source">Lien du dossier Google Drive</label>
                        <input id="drive-source" type="url" required maxLength={600} placeholder="https://drive.google.com/drive/folders/…"
                          value={sourceDrafts[p.id]?.url || ""} disabled={busy || pending}
                          onChange={e => setSourceDrafts(prev => ({ ...prev, [p.id]: { url: e.target.value, consent: prev[p.id]?.consent || false } }))} />
                        <label className="checkbox-label"><input type="checkbox" checked={sourceDrafts[p.id]?.consent || false} disabled={busy || pending}
                          onChange={e => setSourceDrafts(prev => ({ ...prev, [p.id]: { url: prev[p.id]?.url || "", consent: e.target.checked } }))} />
                          J’ai le droit de fournir ces fichiers et j’autorise leur lecture pour ce projet.</label>
                        <button className="btn secondary" disabled={busy || pending || !sourceDrafts[p.id]?.consent || !sourceDrafts[p.id]?.url}>Lire les documents du projet</button>
                      </form>
                      {p.pipeline?.sources && <div aria-live="polite">
                        <p>{p.pipeline.sources.status === "READ" ? "Sources lues" : p.pipeline.sources.status === "queued" ? "Lecture en cours" : "Lecture à vérifier"} · {p.pipeline.sources.pages || 0} pages ou sections</p>
                        <ul>{p.pipeline.sources.files.map((file, index) => <li key={index}>{file.name} · version {file.version}</li>)}</ul>
                      </div>}
                      <div className="pipeline-progress" role="status">
                        {p.pipeline?.state === "READY" ? "Brief complet et cohérent — vous pouvez demander une maquette de test."
                          : p.pipeline?.state === "BUILDING" ? "Construction et revue de la maquette en cours."
                          : p.pipeline?.state === "REVIEW_REQUIRED" ? "Maquette revue — validation humaine requise avant livraison."
                          : p.pipeline?.state === "DELIVERED" ? "Maquette livrée dans votre espace."
                          : p.pipeline?.state === "STOPPED" ? "Projet arrêté. Reprenez la discussion pour continuer."
                          : p.pipeline?.state === "BLOCKED" ? "Une vérification est nécessaire. Précisez votre demande ou contactez le support."
                          : "Échangez avec l’assistant pour compléter le brief avant la construction."}
                        {p.pipeline?.questions?.length ? <ul>{p.pipeline.questions.slice(0,2).map(q => <li key={q}>{q}</li>)}</ul> : null}
                      </div>
                      {p.pipeline?.state === "READY" && <details open>
                        <summary>Brief vérifié — à relire avant la construction</summary>
                        <dl>{p.pipeline.facts?.map(fact => <div key={fact.field}><dt>{({ goal: "Objectif", audience: "Public", site_type: "Type de site", pages: "Pages", features: "Fonctionnalités", constraints: "Contraintes" } as Record<string, string>)[fact.field] || fact.field}</dt><dd>{fact.value}{fact.quote && <blockquote>{fact.quote}</blockquote>}<small>Source : {fact.source}</small></dd></div>)}</dl>
                        <p>Le bouton suivant confirme ce brief et autorise la construction d’un prototype sur l’hébergement de test. Sa livraison restera soumise à une revue et une validation humaine.</p>
                        <p>Le sous-domaine de test est partagé avec les essais du pipeline mail. Toute personne qui possède le lien de la maquette pourra l’ouvrir. Votre dossier Drive et ses identifiants ne sont pas publiés.</p>
                        <button className="btn primary" disabled={busy || pending} onClick={() => void act({ type: "generate_preview" })}>Valider ce brief et construire la maquette</button>
                      </details>}
                      {p.pipeline?.state === "STOPPED"
                        ? <button className="btn secondary" disabled={busy || pending} onClick={() => void act({ type: "resume_pipeline" })}>Reprendre la discussion</button>
                        : <button className="text-link" disabled={busy || pending} onClick={() => void act({ type: "stop_pipeline" })}>Arrêter les prochains traitements</button>}
                      {p.pipeline?.state === "BLOCKED" && <button className="btn secondary" onClick={() => open("support")}>Contacter le support</button>}
                    </section>}
                    <div className="unified-chat-layout">
                      <section
                        className="card chat-card site-chat-card"
                        aria-label={`Conversation for ${p.name}`}
                      >
                        <div className="chat-heading">
                          <span className="chat-logo">
                            <Asterisk size={23} />
                          </span>
                          <div>
                            <h2>Atelier assistant</h2>
                            <p>One conversation for {p.name}</p>
                          </div>
                          <Badge tone="neutral">{connected ? "Assistant connecté" : "Guided preview"}</Badge>
                        </div>
                        <div
                          className="messages"
                          role="log"
                          aria-label="Website conversation"
                          aria-live="polite"
                        >
                          <div className="conversation-welcome">
                            <span>
                              <ShieldCheck size={13} />
                              Ask questions before paying
                            </span>
                            <p>
                              This conversation belongs to this website. Sharing
                              an idea never starts a paid job.
                            </p>
                          </div>
                          {!p.messages.some(
                            (m, index) =>
                              m.role === "assistant" &&
                              (m.kind === "initial_quote" ||
                                (index === 0 && !m.kind)),
                          ) && creationQuote}
                          {p.messages.map((m, index) => {
                            const request = m.requestId
                              ? p.requests.find((r) => r.id === m.requestId)
                              : undefined;
                            return (
                              <div key={m.id} className={`message ${m.role}`}>
                                <span className="message-avatar">
                                  {m.role === "assistant" ? (
                                    <Asterisk size={17} />
                                  ) : (
                                    displayName.charAt(0).toUpperCase()
                                  )}
                                </span>
                                <div className="message-content">
                                  <small>
                                    {m.role === "assistant" ? "Atelier" : "You"}
                                  </small>
                                  <p>{m.text}</p>
                                  {m.role === "assistant" &&
                                    (m.kind === "initial_quote" ||
                                      (index === 0 && !m.kind)) &&
                                    creationQuote}
                                  {request &&
                                    m.kind === "request" &&
                                    requestCard(request)}
                                </div>
                              </div>
                            );
                          })}
                          {p.requests.filter(
                            (r) =>
                              !p.messages.some(
                                (m) =>
                                  m.requestId === r.id && m.kind === "request",
                              ),
                          ).length > 0 && (
                            <div className="retained-offers">
                              <small>Saved changes for this website</small>
                              {p.requests
                                .filter(
                                  (r) =>
                                    !p.messages.some(
                                      (m) =>
                                        m.requestId === r.id &&
                                        m.kind === "request",
                                    ),
                                )
                                .map(requestCard)}
                            </div>
                          )}
                          {p.activity.length > 0 && <details className="retained-offers">
                            <summary>Saved website activity ({p.activity.length})</summary>
                            <p>Retained events include older changes recorded before this conversation view.</p>
                            <ol aria-label="Saved website activity">
                              {p.activity.map(event => <li key={event.id}>
                                <time dateTime={event.at}>{new Date(event.at).toLocaleString()}</time>
                                {" · "}{event.text}
                              </li>)}
                            </ol>
                          </details>}
                          <div ref={endOfChat} />
                        </div>
                        <form
                          className="chat-form unified-composer"
                          onSubmit={sendMessage}
                        >
                          <div
                            className="chat-service-options"
                            role="group"
                            aria-label="Conversation topic"
                          >
                            {services.map((service) => (
                              <button
                                type="button"
                                key={service.value}
                                aria-pressed={draft.category === service.value}
                                className={
                                  draft.category === service.value
                                    ? "selected"
                                    : ""
                                }
                                onClick={() => {
                                  changeDraft({ category: service.value });
                                  composer.current?.focus();
                                }}
                                disabled={busy}
                              >
                                {service.label}
                              </button>
                            ))}
                          </div>
                          <label className="sr-only" htmlFor="chat">
                            Message for {p.name}
                          </label>
                          <textarea
                            ref={composer}
                            id="chat"
                            value={draft.text}
                            onChange={(e) =>
                              changeDraft({ text: e.target.value })
                            }
                            placeholder={`What would you like to do with ${p.name}?`}
                            minLength={3}
                            maxLength={3000}
                            disabled={busy}
                            required
                            rows={3}
                          />
                          <p className="composer-context">
                            {
                              services.find(
                                (service) => service.value === draft.category,
                              )?.detail
                            }
                          </p>
                          <div className="composer-send">
                            <span>
                              For {p.name} · no work starts from a message
                            </span>
                            <button
                              className="send-btn"
                              disabled={busy || pending || draft.text.trim().length < 3}
                              aria-label="Send message"
                            >
                              {busy ? (
                                <LoaderCircle className="spin" size={17} />
                              ) : (
                                <Send size={17} />
                              )}
                            </button>
                          </div>
                        </form>
                      </section>
                      <aside className="website-context">
                        <section className="card site-context-card">
                          <span className="context-leaf">
                            <Leaf size={22} />
                          </span>
                          <h2>{p.name}</h2>
                          <p>{p.brief.description}</p>
                          <div className="context-row">
                            <span>Website status</span>
                            <Badge tone="neutral">Not published</Badge>
                          </div>
                          <div className="context-row">
                            <span>Hosting & care</span>
                            <strong>Not started</strong>
                          </div>
                          <div className="context-row">
                            <span>Proposed pages</span>
                            <strong>{p.brief.pages.length}</strong>
                          </div>
                          <div className="context-reference">
                            <span>Website reference</span>
                            <code title={p.id}>{p.id.slice(0, 8)}</code>
                          </div>
                          <button
                            className="text-link"
                            onClick={() => exportProject(p)}
                          >
                            Export this website <ArrowDownToLine size={13} />
                          </button>
                        </section>
                        <div className="simple-note">
                          <ShieldCheck size={18} />
                          <p>
                            {connected ? "Vos échanges et maquettes restent dans ce site. La génération démarre avec votre clic ; l’approbation ne publie rien." : "Quotes, changes and approvals stay in this conversation. Integrations are not connected."}
                          </p>
                        </div>
                      </aside>
                    </div>
                  </>
                ) : (
                  <section className="card empty-state">
                    <CircleHelp size={30} />
                    <h2>This website is unavailable.</h2>
                    <p>
                      Choose a website from your overview to open its
                      conversation.
                    </p>
                    {button(
                      "Back to your websites",
                      () => navigate("Overview"),
                      "secondary",
                    )}
                  </section>
                ))}

              {view === "Plan & billing" && (
                <>
                  <div className="billing-grid">
                    <section className="card plan-card">
                      <div className="card-heading">
                        <div>
                          <span className="eyebrow">
                            THE START OF SOMETHING GOOD
                          </span>
                          <h2>Website creation</h2>
                        </div>
                        <Badge tone="neutral">One time</Badge>
                      </div>
                      <div className="price">
                        €499<span>draft price</span>
                      </div>
                      <p>A thoughtful home for your business online.</p>
                      <ul>
                        {[
                          "Discuss your idea before paying",
                          "A standard business website",
                          "Preview, revisions and your approval",
                          "Final scope agreed before checkout",
                        ].map((t) => (
                          <li key={t}>
                            <Check size={16} />
                            {t}
                          </li>
                        ))}
                      </ul>
                      {button(
                        "Choose a website to discuss",
                        () => navigate("Overview"),
                        "secondary",
                      )}
                    </section>
                    <section className="card plan-card featured">
                      <div className="card-heading">
                        <div>
                          <span className="eyebrow">
                            A LITTLE CARE GOES A LONG WAY
                          </span>
                          <h2>Hosting & maintenance</h2>
                        </div>
                        <Sprout size={26} />
                      </div>
                      <div className="price">
                        €39<span>/ month, proposed per website</span>
                      </div>
                      <p>A little care for every website you grow.</p>
                      <ul>
                        {[
                          "Hosting and domain configuration",
                          "Monitoring, backups and technical care",
                          "Up to 2 eligible content edits / month",
                          "Begins only after checkout and launch",
                        ].map((t) => (
                          <li key={t}>
                            <Check size={16} />
                            {t}
                          </li>
                        ))}
                      </ul>
                      <div className="plan-not-active">
                        <Clock3 size={16} />
                        No subscriptions have started
                      </div>
                    </section>
                  </div>
                  <section className="card service-menu">
                    <div className="card-heading">
                      <div>
                        <h2>A little extra, in the same conversation.</h2>
                        <p>
                          Discuss changes and review each quote in your
                          website’s chat.
                        </p>
                      </div>
                      <Badge tone="neutral">Draft catalog</Badge>
                    </div>
                    <div>
                      {[
                        [
                          "An additional standard page",
                          "One page in the existing design.",
                          "€99",
                        ],
                        [
                          "A design refresh",
                          "A scoped direction, with a final quote.",
                          "From €149",
                        ],
                        [
                          "Something more advanced",
                          "Features and integrations, scoped separately.",
                          "Custom quote",
                        ],
                      ].map(([t, d, price]) => (
                        <div key={t}>
                          <span>
                            <strong>{t}</strong>
                            <small>{d}</small>
                          </span>
                          <b>{price}</b>
                        </div>
                      ))}
                    </div>
                  </section>
                  {projects.length > 0 && (
                    <section className="card website-billing-list">
                      <div className="card-heading">
                        <div>
                          <h2>Your websites</h2>
                          <p>Review each offer in its own conversation.</p>
                        </div>
                      </div>
                      {projects.map((project) => (
                        <a href={`#/sites/${project.id}`} key={project.id}>
                          <span>
                            <strong>{project.name}</strong>
                            <small>
                              {project.initialQuote.status === "draft"
                                ? "Draft quote · no payment collected"
                                : "Acceptance recorded · payment pending"}
                            </small>
                          </span>
                          <ArrowRight size={16} />
                        </a>
                      ))}
                    </section>
                  )}
                  <p className="billing-footnote">
                    Draft prices, tax treatment, final scope and the two-edit
                    allowance need confirmation before a real checkout. This
                    preview cannot create payments, invoices or subscriptions.
                  </p>
                </>
              )}

              {view === "Settings" && (
                <div className="settings-grid">
                  <section className="card setting-card">
                    <h2>Your websites, in your hands.</h2>
                    <p>
                      Export each website’s brief, retained conversation, quotes
                      and approval history.
                    </p>
                    {projects.length ? (
                      projects.map((project) => (
                        <div className="integration-row" key={project.id}>
                          <span>{project.name}</span>
                          <button
                            className="text-link"
                            onClick={() => exportProject(project)}
                            aria-label={`Export ${project.name}`}
                          >
                            Export <ArrowDownToLine size={14} />
                          </button>
                        </div>
                      ))
                    ) : (
                      <small>
                        Your websites will appear here once you create a brief.
                      </small>
                    )}
                  </section>
                  <section className="card setting-card">
                    <h2>Connected services</h2>
                    <p>
                      {connected ? "L’assistant et les maquettes sont connectés. Paiement et publication restent soumis à une étape distincte." : "The portal remains independent of the production systems."}
                    </p>
                    {[
                      "Payment provider",
                      "AI assistant",
                      "n8n / builder",
                      "Hosting & publishing",
                      "Support delivery",
                      "File uploads",
                    ].map((t) => (
                      <div className="integration-row" key={t}>
                        <span>{t}</span>
                        <Badge tone="neutral">{connected && ["AI assistant", "n8n / builder"].includes(t) ? pipelineConfig.available ? "Pipeline de test connecté" : "Maquette privée connectée" : t === "File uploads" && pipelineConfig.available ? "Sources via Google Drive" : "Not connected"}</Badge>
                      </div>
                    ))}
                  </section>
                  <section className="card setting-card">
                    <h2>Account</h2>
                    <p>{displayName}</p>
                    <p>
                      Your portal account owns your website list. Each website
                      has a separate conversation and a stable project
                      reference.
                    </p>
                    <a
                      className="text-link"
                      href={BASE + "/logout"}
                      onClick={signOut}
                    >
                      Sign out <ExternalLink size={14} />
                    </a>
                  </section>
                </div>
              )}
            </>
          )}
          <footer className="page-footer">
            <span>
              <Asterisk size={14} />A little less admin. A lot more you.
            </span>
            <button onClick={() => open("help")}>
              Made with care <Leaf size={12} />
            </button>
          </footer>
        </main>
      </div>
      {notice && (
        <div className="toast" role="status">
          <CheckCheck size={18} />
          {notice}
        </div>
      )}
      <dialog
        ref={dialog}
        onCancel={() => setModal(null)}
        onClick={(e) => {
          if (e.target === dialog.current && !busy) setModal(null);
        }}
      >
        <div
          className={`modal-content ${modal === "preview" ? "preview-modal" : ""}`}
        >
          <button
            className="modal-close icon-btn"
            aria-label="Close dialog"
            onClick={() => setModal(null)}
          >
            <X size={21} />
          </button>
          {error && modal && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {modal === "new" && (
            <>
              <div className="eyebrow">
                YOUR NEXT CHAPTER · STEP {step} OF 2
              </div>
              <h2>
                Tell us a little
                <br />
                <em>about your business.</em>
              </h2>
              <p className="modal-intro">
                A few details now. A website that feels like you later.
              </p>
              <form
                onSubmit={(e: FormEvent<HTMLFormElement>) => {
                  e.preventDefault();
                  if (step === 1) setStep(2);
                  else void create();
                }}
              >
                {step === 1 ? (
                  <>
                    <label>
                      Business name
                      <input
                        autoFocus
                        value={brief.businessName}
                        onChange={(e) =>
                          setBrief({ ...brief, businessName: e.target.value })
                        }
                        placeholder="e.g. Studio Botanique"
                        minLength={2}
                        maxLength={160}
                        required
                      />
                    </label>
                    <label>
                      What do you do?
                      <input
                        value={brief.industry}
                        onChange={(e) =>
                          setBrief({ ...brief, industry: e.target.value })
                        }
                        placeholder="e.g. An independent floral studio"
                        minLength={2}
                        maxLength={160}
                        required
                      />
                    </label>
                    <label>
                      Tell us your story
                      <textarea
                        rows={4}
                        value={brief.description}
                        onChange={(e) =>
                          setBrief({ ...brief, description: e.target.value })
                        }
                        placeholder="What makes your business special? What should your website help you achieve?"
                        minLength={20}
                        maxLength={4000}
                        required
                      />
                    </label>
                    <label>
                      Who is your website for?
                      <input
                        value={brief.audience}
                        onChange={(e) =>
                          setBrief({ ...brief, audience: e.target.value })
                        }
                        placeholder="Your customers, community or audience"
                        minLength={3}
                        maxLength={300}
                        required
                      />
                    </label>
                  </>
                ) : (
                  <>
                    <fieldset>
                      <legend>Which pages do you have in mind?</legend>
                      <div className="page-options">
                        {[
                          "Home",
                          "About",
                          "Services",
                          "Contact",
                          "Gallery",
                          "FAQ",
                        ].map((page) => (
                          <label key={page}>
                            <input
                              type="checkbox"
                              checked={brief.pages.includes(
                                page as Brief["pages"][number],
                              )}
                              onChange={(e) =>
                                setBrief({
                                  ...brief,
                                  pages: e.target.checked
                                    ? [
                                        ...brief.pages,
                                        page as Brief["pages"][number],
                                      ]
                                    : brief.pages.filter((t) => t !== page),
                                })
                              }
                            />
                            {page}
                          </label>
                        ))}
                      </div>
                      <small>
                        Choose at least one. Final page scope will be confirmed
                        before checkout.
                      </small>
                    </fieldset>
                    <label>
                      What should it feel like?
                      <select
                        value={brief.style}
                        onChange={(e) =>
                          setBrief({
                            ...brief,
                            style: e.target.value as Brief["style"],
                          })
                        }
                      >
                        <option>Warm & natural</option>
                        <option>Clean & modern</option>
                        <option>Bold & expressive</option>
                      </select>
                    </label>
                    <label>
                      Existing website or reference (optional)
                      <input
                        type="url"
                        value={brief.website}
                        onChange={(e) =>
                          setBrief({ ...brief, website: e.target.value })
                        }
                        placeholder="https://"
                        maxLength={1000}
                      />
                    </label>
                    <div className="quote-summary">
                      <span>
                        Website creation <strong>€499</strong>
                      </span>
                      <span>
                        Hosting & maintenance after launch{" "}
                        <strong>€39 / month</strong>
                      </span>
                      <p>
                        Draft pricing. Saving your brief does not accept a
                        quote, start work or collect payment.
                      </p>
                    </div>
                  </>
                )}
                <div className="form-actions">
                  {step === 2 && (
                    <button
                      type="button"
                      className="btn secondary"
                      onClick={() => setStep(1)}
                    >
                      Back
                    </button>
                  )}
                  <button
                    className="btn primary"
                    disabled={busy || (step === 2 && !brief.pages.length)}
                  >
                    {busy
                      ? "Saving…"
                      : step === 1
                        ? "A little more about your website"
                        : "Open my website assistant"}
                    <ArrowRight size={16} />
                  </button>
                </div>
              </form>
            </>
          )}
          {modal === "support" && p && <SupportForm key={p.id} project={p} refresh={refresh} />}
          {modal === "preview" && p && (
            <>
              <div className="eyebrow">YOUR IDEAS, TAKING SHAPE</div>
              <h2>
                A first <em>impression.</em>
              </h2>
              <p className="modal-intro">
                {pending ? p.integration?.kind === "generate_preview" ? "Votre maquette est en préparation. Vous pouvez fermer cette fenêtre et revenir." : "Votre brief et vos sources sont en cours d’analyse. Aucune nouvelle construction n’est lancée." : p.preview?.generated ? `Maquette IA v${p.preview.version} · ${p.preview.externalUrl ? "hébergement de test" : "privée"}, à examiner avant approbation.` : previewFailure ? "Aucune nouvelle maquette n’est disponible." : `Concept v${p.preview?.version || "—"} · aperçu de démonstration.`}
              </p>
              {previewFailure && !pending && <div className="error" role="alert">
                {p.integration?.status === "stale" ? "Cette génération a été écartée car le contexte du site a changé." : p.integration?.status === "unknown" ? "Le résultat de la génération n’a pas été confirmé." : "La génération de la maquette a échoué."}
                {p.preview ? " La dernière version disponible est conservée ci-dessous." : " Aucun aperçu n’a été créé."}
                {" Aucune relance automatique n’a lieu."}
              </div>}
              {previewFailure && <button className="btn secondary" onClick={() => open("support")}>Contacter le support <MessageCircle size={15} /></button>}
              {pipelineConfig.available && !p.preview && <div className="pipeline-progress" role="status">
                {p.pipeline?.state === "REVIEW_REQUIRED" ? "La maquette attend une validation humaine avant sa livraison. Vous retrouverez ici son lien dès validation."
                  : pending ? "Votre demande est en cours de traitement. Aucun résultat non vérifié n’est affiché."
                  : "Complétez et relisez le brief avec l’assistant avant de demander la construction de votre maquette."}
              </div>}
              {(p.preview || !pipelineConfig.available && !pending && !previewFailure) && <div className="browser-frame">
                <div className="browser-toolbar">
                  <div className="browser-dots">
                    <i />
                    <i />
                    <i />
                  </div>
                  <span>{p.preview?.externalUrl ? "Maquette sur l’hébergement de test" : "Private concept preview"}</span>
                  <Monitor size={13} />
                </div>
                {p.preview?.externalUrl ? <div className="external-preview">
                  <p>Cette maquette de test suit votre brief et les sources fournies. Sa réalisation, sa revue et sa livraison ont été vérifiées. Toute personne qui possède son lien peut l’ouvrir. Son approbation ne publie pas de site commercial.</p>
                  <a className="btn primary" href={p.preview.externalUrl} target="_blank" rel="noopener noreferrer">Ouvrir la maquette de test <ExternalLink size={15} /></a>
                </div> : p.preview?.generated ? <iframe className="generated-preview" title={`Maquette ${p.name} version ${p.preview.version}`} sandbox="" src={`${BASE}/api/projects/${p.id}/preview/${p.preview.version}`} /> : !pending && !pipelineConfig.available && <Concept project={p} large />}
              </div>}
              {!pending && !previewFailure && p.preview?.status === "awaiting_review" ? (
                <div className="review-controls">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={confirmApproval}
                      onChange={(e) => setApprovedPreviewKey(e.target.checked ? previewKey : "")}
                    />
                    I approve this concept version. I understand this does not
                    publish a website.
                  </label>
                  <div className="form-actions">
                    <button
                      className="btn primary"
                      disabled={busy || pending || !confirmApproval}
                      onClick={() =>
                        void act(
                          {
                            type: "approve_preview",
                            previewVersion: p.preview!.version,
                          },
                          "Approval recorded. Nothing has been published.",
                        )
                      }
                    >
                      Approve concept <Check size={15} />
                    </button>
                  </div>
                  <form
                    onSubmit={async (e) => {
                      e.preventDefault();
                      if (
                        await act(
                          {
                            type: "preview_feedback",
                            previewVersion: p.preview!.version,
                            text: feedback,
                          },
                          "Your feedback is saved.",
                        )
                      )
                        setFeedback("");
                    }}
                  >
                    <label>
                      Something you’d like to change?
                      <textarea
                        rows={2}
                        value={feedback}
                        onChange={(e) => setFeedback(e.target.value)}
                        placeholder="Share your feedback on this version…"
                        minLength={3}
                        maxLength={3000}
                        required
                      />
                    </label>
                    <button
                      className="btn secondary"
                      disabled={busy || pending || feedback.trim().length < 3}
                    >
                      Request changes <ArrowRight size={14} />
                    </button>
                  </form>
                </div>
              ) : !pending ? (
                <div className="review-controls">
                  {p.preview && <Badge>{labels[p.preview.status]}</Badge>}
                  {p.preview?.feedback && <p>{p.preview.feedback}</p>}
                  <p>
                    {pipelineConfig.available
                      ? "Chaque nouvelle maquette nécessite une nouvelle analyse du brief, votre accord de construction et une validation de livraison."
                      : "No production job or publication was started. Preparing another concept will create a new version requiring its own approval."}
                  </p>
                  {pipelineConfig.available ? button("Revoir le brief avant une nouvelle version", () => {
                    setModal(null);
                    document.getElementById("project-source-review")?.scrollIntoView({ behavior: "smooth" });
                  }, "secondary") : button(
                    previewFailure ? "Réessayer la génération" : "Prepare a new concept version",
                    () =>
                      void act(
                        { type: "generate_preview" },
                        connected ? "Nouvelle maquette demandée." : "New concept version prepared.",
                      ),
                    "secondary",
                  )}
                </div>
              ) : null}
            </>
          )}
          {modal === "brief" && p && (
            <>
              <h2>
                Your website <em>brief.</em>
              </h2>
              <p>{p.brief.description}</p>
              <div className="brief-details">
                <p>
                  <strong>Business</strong>
                  {p.name} · {p.brief.industry}
                </p>
                <p>
                  <strong>Audience</strong>
                  {p.brief.audience}
                </p>
                <p>
                  <strong>Pages</strong>
                  {p.brief.pages.join(", ")}
                </p>
                <p>
                  <strong>Style</strong>
                  {p.brief.style}
                </p>
              </div>
            </>
          )}
          {modal === "help" && (
            <>
              {p ? <button className="btn secondary" onClick={() => open("support")}>Contacter le support pour ce site <MessageCircle size={15} /></button> : <p>Pour contacter le support, ouvrez le site concerné depuis votre liste de sites, puis choisissez « Contacter le support ».</p>}
              <div className="eyebrow">A LITTLE GUIDANCE</div>
              <h2>One website. One conversation.</h2>
              <p className="modal-intro">Everything you need to get started.</p>
              <ol className="help-steps">
                <li>
                  <span>1</span>
                  <div>
                    <strong>Find your websites in Overview.</strong>
                    <p>
                      Each website has its own brief, messages, quotes and
                      approvals. Click one to open its assistant.
                    </p>
                  </div>
                </li>
                <li>
                  <span>2</span>
                  <div>
                    <strong>Talk through your idea before paying.</strong>
                    <p>
                      No payment or subscription starts from creating a brief or
                      sending a message.
                    </p>
                  </div>
                </li>
                <li>
                  <span>3</span>
                  <div>
                    <strong>Keep changes in the same chat.</strong>
                    <p>
                      Choose a conversation topic to describe a change and
                      review its draft quote in the conversation.
                    </p>
                  </div>
                </li>
                <li>
                  <span>4</span>
                  <div>
                    <strong>{connected ? "Un espace privé pour préparer votre site." : "This is a guided portal preview."}</strong>
                    <p>
                      {connected ? pipelineConfig.available ? "L’assistant utilise le brief et vos sources Drive autorisées. Après votre accord explicite, une maquette est construite sur l’hébergement de test puis revue avant livraison. Toute personne ayant son lien peut l’ouvrir. Aucun paiement ni publication commerciale automatique." : "L’assistant répond à vos messages. Le bouton de génération prépare une maquette IA privée à examiner. Son approbation ne déclenche ni paiement ni publication." : "Replies are guided and concepts use a template. Integrations are not connected."}
                    </p>
                  </div>
                </li>
              </ol>
              <button className="btn primary" onClick={() => setModal(null)}>
                Got it <Check size={16} />
              </button>
            </>
          )}
        </div>
      </dialog>
    </div>
  );
}
