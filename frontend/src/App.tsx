import { FormEvent, useEffect, useMemo, useState } from "react";

type Patient = { source?: string | null; followup_status?: string; patient_id: string; patient_ref: string; full_name: string; mobile_number: string; date_of_birth: string | null; gender: string | null; email: string | null; address: string | null; registration_flow: "DISCHARGE" | "OPD_FOLLOWUP" | "SURGERY_FOLLOWUP"; visit_date: string | null; surgery_date: string | null; confirmed_surgery_date?: string | null; department: string | null; doctor_id: string | null; doctor_name?: string | null; status: string; created_at: string };
type Episode = { episode_id: string; episode_ref: string; patient_id: string; department: string; treating_doctor: string | null; discharge_date: string; care_start_date: string; care_end_date: string; status: string };
type Task = { task_id: string; episode_id: string; task_type: string; title: string; instructions: string | null; start_date: string; end_date: string; selected_slots: string[]; status: string };
type User = { full_name: string; email: string; role: string };
type Doctor = { doctor_id: string; full_name: string; department: string; is_active?: boolean };
type CallNote = { note_id: string; status: string; call_outcome: string; notes: string; called_at: string; next_followup_date?: string | null; confirmed_surgery_date?: string | null };
type WhatsAppMedia = {
  media_record_id: string;
  event_id: string;
  patient_id: string | null;
  direction: string;
  caption: string | null;
  mime_type: string;
  byte_size: number | null;
  created_at: string | null;
  url: string;
  url_expires_in: number;
};
type WhatsAppEvent = { event_id: string; direction: string; phone_number: string; message_text: string; status: string; received_at: string | null; patient_id: string | null; patient_ref: string | null; patient_name: string | null; episode_id: string | null; episode_ref: string | null; department: string | null; needs_review: boolean; attention_flag: boolean; attention_note: string | null; attention_updated_at: string | null };
type JourneyEvent = { id: string; kind: string; category: "care" | "whatsapp" | "followups" | "alerts"; title: string; description: string; occurred_at: string | null; status: string | null; details: Record<string, unknown> };
type PatientJourney = { patient: { patient_id: string; patient_ref: string; full_name: string; registration_flow: string }; total_events: number; events: JourneyEvent[] };
type Kpis = { total_new_patients: number; opd_planned: number; opd_attended: number; opd_pending: number; surgery_planned: number; surgery_confirmed: number; surgery_refused: number; post_discharge_active_episodes: number };
const today = (() => { const d = new Date(); const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return local.toISOString().slice(0, 10); })();
const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");
async function api<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init?.headers || {}) } });
  if (!r.ok) { const b = await r.json().catch(() => null); throw new Error(b?.detail || `Request failed (${r.status})`); }
  return r.json();
}
const slots = [{ value: "EARLY_MORNING", label: "Early morning", time: "05:00–08:00" }, { value: "MORNING", label: "Morning", time: "08:00–12:00" }, { value: "AFTERNOON", label: "Afternoon", time: "12:00–16:00" }, { value: "EVENING", label: "Evening", time: "16:00–20:00" }, { value: "NIGHT", label: "Night", time: "20:00–23:00" }];
const departments = ["Orthopaedics", "ENT", "Gynaecology", "General Medicine", "General Surgery", "Cardiology", "Neurology", "Paediatrics", "Urology", "Neurosurgery", "Periodontics", "General Surgeon", "General Physician", "Other"];
const taskTypes = ["MEDICATION", "DIAGNOSTIC", "OPD", "NURSE_VISIT", "PHYSIOTHERAPY", "CHECK_IN", "OTHER"];

export default function App() {
  const [token, setToken] = useState(localStorage.getItem("careplus_token") || "");
  const [user, setUser] = useState<User | null>(null);
  const [login, setLogin] = useState({ email: "", password: "" });
  const [patients, setPatients] = useState<Patient[]>([]);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [managedDoctors, setManagedDoctors] = useState<Doctor[]>([]);
  const [doctorForm, setDoctorForm] = useState({ full_name: "", department: "Orthopaedics" });
  const [opdDepartmentFilter, setOpdDepartmentFilter] = useState("");
  const [opdDoctorFilter, setOpdDoctorFilter] = useState("");
  const [surgeryDepartmentFilter, setSurgeryDepartmentFilter] = useState("");
  const [surgeryDoctorFilter, setSurgeryDoctorFilter] = useState("");
  const [callNotes, setCallNotes] = useState<CallNote[]>([]);
  const [notePatient, setNotePatient] = useState<Patient | null>(null);
  const [noteForm, setNoteForm] = useState({ status: "CALLED", call_outcome: "CONTACTED", notes: "", next_followup_date: "", confirmed_surgery_date: "" });
  const [dashboardStart, setDashboardStart] = useState(today);
  const [dashboardEnd, setDashboardEnd] = useState(today);
  const [dashboardDepartment, setDashboardDepartment] = useState("");
  const [dashboardDoctor, setDashboardDoctor] = useState("");
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [whatsappEvents, setWhatsappEvents] = useState<WhatsAppEvent[]>([]);
  const [whatsappMedia, setWhatsappMedia] = useState<WhatsAppMedia[]>([]);
  const [whatsappDepartment, setWhatsappDepartment] = useState("");
  const [whatsappDoctor, setWhatsappDoctor] = useState("");
  const [whatsappAttentionFilter, setWhatsappAttentionFilter] = useState("ALL");
  const [doctorComments, setDoctorComments] = useState<Record<string, string>>({});
  const [whatsappAssignments, setWhatsappAssignments] = useState<Record<string, { patient_id: string; episode_id: string }>>({});
  const [assigningWhatsAppEvent, setAssigningWhatsAppEvent] = useState("");
  const [selectedPatientId, setSelectedPatientId] = useState("");
  const [selectedEpisodeId, setSelectedEpisodeId] = useState("");
  const [tab, setTab] = useState("patients");
  const [journey, setJourney] = useState<PatientJourney | null>(null);
  const [journeyFilter, setJourneyFilter] = useState("all");
  const [journeyLoading, setJourneyLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const emptyPatientForm = () => ({ full_name: "", mobile_number: "", date_of_birth: "", gender: "", email: "", address: "", registration_flow: "DISCHARGE" as "DISCHARGE" | "OPD_FOLLOWUP" | "SURGERY_FOLLOWUP", visit_date: "", surgery_date: "", department: "", doctor_id: "", source: "Walk In" });
  const [pf, setPf] = useState(emptyPatientForm);
  const emptyEpisodeForm = (patient_id = "") => ({ patient_id, department: "Orthopaedics", treating_doctor: "", doctor_id: "", admission_date: "", discharge_date: "", care_start_date: "", care_end_date: "", reason_for_care: "" });
  const [ef, setEf] = useState(emptyEpisodeForm());
  const emptyTaskForm = (episode_id = "") => ({ episode_id, task_type: "MEDICATION", title: "", instructions: "", start_date: "", end_date: "", selected_slots: [] as string[] });
  const [tf, setTf] = useState(emptyTaskForm());

  const selectedPatient = patients.find(p => p.patient_id === selectedPatientId) || null;
  const patientEpisodes = useMemo(() => episodes.filter(ep => ep.patient_id === selectedPatientId), [episodes, selectedPatientId]);
  const patientTasks = useMemo(() => { const ids = new Set(patientEpisodes.map(ep => ep.episode_id)); return tasks.filter(t => ids.has(t.episode_id)); }, [tasks, patientEpisodes]);
  const visiblePatients = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return patients;
    return patients.filter(p => [p.full_name, p.patient_ref, p.mobile_number].some(v => (v || "").toLowerCase().includes(term)));
  }, [patients, search]);

  async function deleteRecord(path: string, label: string) {
    const reason = window.prompt(`Why are you deleting this ${label}? This reason will be recorded in the audit log.`);
    if (reason === null) return;
    if (reason.trim().length < 3) { setError("Please enter a deletion reason of at least 3 characters."); return; }
    if (!window.confirm(`Delete this ${label}? This cannot be undone. Linked records may prevent deletion.`)) return;
    setError(""); setMessage("");
    try {
      await api(path, token, { method: "DELETE", body: JSON.stringify({ reason: reason.trim() }) });
      if (path.startsWith("/api/patients/") && selectedPatientId === path.split("/").pop()) {
        setSelectedPatientId(""); setSelectedEpisodeId(""); setNotePatient(null); setCallNotes([]);
      }
      if (path.startsWith("/api/followups/") && notePatient?.patient_id === path.split("/").pop()) {
        setNotePatient(null); setCallNotes([]);
      }
      await refresh();
      setMessage(`${label} deleted successfully.`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function refresh() {
    const [p, e, t] = await Promise.all([api<Patient[]>("/api/patients", token), api<Episode[]>("/api/episodes", token), api<Task[]>("/api/tasks", token)]);
    setPatients(p); setEpisodes(e); setTasks(t);
    const ds = await api<Doctor[]>("/api/doctors?include_inactive=true", token).catch(() => [] as Doctor[]); setManagedDoctors(ds);
  }
  useEffect(() => {
    if (!token) return;
    api<User>("/api/auth/me", token).then(setUser).then(refresh).catch(e => { setError(e.message); localStorage.removeItem("careplus_token"); setToken(""); });
  }, [token]);
  useEffect(() => {
    if (!token || pf.registration_flow === "DISCHARGE" || !pf.department) {
      setDoctors([]);
      return;
    }
    api<Doctor[]>(`/api/doctors?department=${encodeURIComponent(pf.department)}`, token)
        .then(setDoctors)
        .catch(e => { setDoctors([]); setError((e as Error).message); });
  }, [token, pf.registration_flow, pf.department]);

  useEffect(() => {
    if (!token) {
      setWhatsappMedia([]);
      return;
    }

    if (tab !== "journey" && tab !== "progress" && tab !== "doctorview") {
      return;
    }

    const q = new URLSearchParams();
    if (tab === "journey" && selectedPatientId) {
      q.set("patient_id", selectedPatientId);
    }

    let cancelled = false;
    const path = `/api/whatsapp/media${q.toString() ? `?${q.toString()}` : ""}`;

    api<{ items: WhatsAppMedia[] }>(path, token)
        .then(result => {
          if (!cancelled) setWhatsappMedia(result.items || []);
        })
        .catch(e => {
          if (!cancelled) {
            setWhatsappMedia([]);
            setError(`Could not load WhatsApp images: ${(e as Error).message}`);
          }
        });

    return () => {
      cancelled = true;
    };
  }, [token, tab, selectedPatientId]);

  async function signIn(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try { const r = await api<{ access_token: string; user: User }>("/api/auth/login", "", { method: "POST", body: JSON.stringify(login) }); localStorage.setItem("careplus_token", r.access_token); setTab("patients"); setSelectedPatientId(""); setSelectedEpisodeId(""); setToken(r.access_token); setUser(r.user); setMessage(`Welcome, ${r.user.full_name}`); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  function signOut() { localStorage.removeItem("careplus_token"); setToken(""); setUser(null); setPatients([]); setEpisodes([]); setTasks([]); setSelectedPatientId(""); setSelectedEpisodeId(""); }

  function selectPatient(p: Patient, nextTab = "episodes") {
    setSelectedPatientId(p.patient_id);
    setSelectedEpisodeId("");
    setEf(emptyEpisodeForm(p.patient_id));
    setTf(emptyTaskForm());
    const targetTab = p.registration_flow === "DISCHARGE" ? nextTab : "patients";
    setTab(targetTab);
    setMessage(p.registration_flow === "DISCHARGE"
        ? `Selected patient: ${p.patient_ref} — ${p.full_name}`
        : `Selected ${p.patient_ref} — ${p.full_name}. This patient is registered for ${p.registration_flow === "OPD_FOLLOWUP" ? "OPD follow-up" : "surgery follow-up"}; post-hospitalisation episode/task entry is not needed for this pathway.`);
    setError("");
  }
  async function submitPatient(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try {
      const flow = pf.registration_flow;
      const p = await api<Patient>("/api/patients", token, { method: "POST", body: JSON.stringify({
          ...pf,
          date_of_birth: pf.date_of_birth || null,
          gender: pf.gender || null,
          email: pf.email || null,
          address: pf.address || null,
          visit_date: flow === "OPD_FOLLOWUP" ? pf.visit_date || null : null,
          surgery_date: flow === "SURGERY_FOLLOWUP" ? pf.surgery_date || null : null,
          department: flow !== "DISCHARGE" ? pf.department || null : null,
          doctor_id: flow !== "DISCHARGE" ? pf.doctor_id || null : null,
          source: flow !== "DISCHARGE" ? pf.source : null,
        }) });
      await refresh(); setSelectedPatientId(p.patient_id); setSelectedEpisodeId(""); setEf(emptyEpisodeForm(p.patient_id)); setTf(emptyTaskForm());
      setPf(emptyPatientForm());
      if (flow === "DISCHARGE") {
        setMessage(`Patient registered: ${p.patient_ref}. Continue by creating a visit.`);
        setTab("episodes");
      } else {
        const appointmentDate = flow === "OPD_FOLLOWUP" ? p.visit_date : p.surgery_date;
        setMessage(`Patient registered: ${p.patient_ref}. ${flow === "OPD_FOLLOWUP" ? "OPD follow-up" : "Surgery"} date ${appointmentDate} saved for ${p.department}, doctor ${doctors.find(d => d.doctor_id === p.doctor_id)?.full_name || "selected doctor"}. A reminder preview is due one day before the appointment.`);
        setTab("patients");
      }
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function submitEpisode(e: FormEvent) {
    e.preventDefault();
    setError("");

    if (ef.admission_date && ef.admission_date > ef.discharge_date) {
      setError("Admission date cannot be later than discharge date.");
      return;
    }

    if (ef.care_start_date < ef.discharge_date) {
      setError("Care start date cannot be earlier than discharge date.");
      return;
    }

    if (ef.care_end_date < ef.care_start_date) {
      setError("Care end date cannot be earlier than care start date.");
      return;
    }

    setBusy(true);
    try {
      const ep = await api<Episode>("/api/episodes", token, { method: "POST", body: JSON.stringify({ ...ef, treating_doctor: null, doctor_id: ef.doctor_id || null, patient_id: selectedPatientId || ef.patient_id, admission_date: ef.admission_date || null }) });
      await refresh();
      setSelectedEpisodeId(ep.episode_id);
      setEf(emptyEpisodeForm(selectedPatientId));
      setTf(emptyTaskForm(ep.episode_id));
      setMessage(`Visit ${ep.episode_ref} created. Continue by adding a Reminder Task.`);
      setTab("tasks");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function submitTask(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try { const t = await api<Task>("/api/tasks", token, { method: "POST", body: JSON.stringify(tf) }); setMessage(`Reminder Task created: ${t.title}`); await refresh(); setTf(emptyTaskForm(selectedEpisodeId)); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function preview() { setError(""); try { const r = await api<{ created_count: number; note: string }>("/api/alerts/preview-due", token, { method: "POST" }); setMessage(`${r.created_count} care-task or next-day follow-up reminder preview(s) logged for today. No messages or calls were sent.`); } catch (e) { setError((e as Error).message); } }

  async function loadDoctors() { const ds = await api<Doctor[]>("/api/doctors?include_inactive=true", token); setManagedDoctors(ds); }
  async function loadPatientJourney(patientId = selectedPatientId) {
    if (!patientId) { setJourney(null); return; }
    setJourneyLoading(true);
    try { setJourney(await api<PatientJourney>(`/api/patient-journey/${patientId}`, token)); }
    finally { setJourneyLoading(false); }
  }
  async function loadWhatsAppProgress() { const q = new URLSearchParams(); if (whatsappDepartment) q.set("department", whatsappDepartment); if (whatsappDoctor) q.set("doctor_id", whatsappDoctor); const rows = await api<WhatsAppEvent[]>(`/api/whatsapp/progress?${q.toString()}`, token); setWhatsappEvents(rows); }
  async function sendDoctorComment(w: WhatsAppEvent) { const comment = (doctorComments[w.event_id] || "").trim(); if (!comment) { setError("Enter a comment before sending."); return; } if (!w.patient_id || !w.episode_id) { setError("This message must be linked to a patient and episode before replying."); return; } if (!window.confirm("Send this comment to the patient on WhatsApp?")) return; setBusy(true); setError(""); setMessage(""); try { await api("/api/whatsapp/send", token, { method: "POST", body: JSON.stringify({ patient_id: w.patient_id, episode_id: w.episode_id, message: comment }) }); setDoctorComments(current => ({ ...current, [w.event_id]: "" })); await loadWhatsAppProgress(); setMessage("Doctor comment sent to WhatsApp and recorded in the conversation."); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  async function assignWhatsAppMessage(eventId: string) {
    const selection = whatsappAssignments[eventId];
    if (!selection?.patient_id) { setError("Select a patient before assigning this message."); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      await api(`/api/whatsapp/events/${eventId}/assign`, token, {
        method: "PATCH",
        body: JSON.stringify({ patient_id: selection.patient_id, episode_id: selection.episode_id || null }),
      });
      await loadWhatsAppProgress();
      setMessage("WhatsApp message assigned. The association has been saved.");
      setAssigningWhatsAppEvent("");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function updateWhatsAppAttention(w: WhatsAppEvent) {
    let note: string | null = null;
    if (!w.attention_flag) {
      const entered = window.prompt("Why does this message need follow-up? Enter a brief staff note:");
      if (entered === null) return;
      if (!entered.trim()) { setError("A short staff note is required to flag a message."); return; }
      note = entered.trim();
    } else {
      if (!window.confirm("Resolve this follow-up flag? The last staff note will be retained.")) return;
    }
    setError(""); setMessage("");
    try {
      await api(`/api/whatsapp/events/${w.event_id}/attention`, token, {
        method: "PATCH",
        body: JSON.stringify({ attention_flag: !w.attention_flag, attention_note: note }),
      });
      await loadWhatsAppProgress();
      setMessage(w.attention_flag ? "Follow-up flag resolved." : "Message flagged for staff follow-up.");
    } catch (e) { setError((e as Error).message); }
  }
  async function createDoctor(e: FormEvent) { e.preventDefault(); setBusy(true); setError(""); try { await api<Doctor>("/api/doctors", token, { method: "POST", body: JSON.stringify(doctorForm) }); setDoctorForm({ full_name: "", department: "Orthopaedics" }); await loadDoctors(); await refresh(); setMessage("Doctor added successfully."); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  async function toggleDoctor(d: Doctor) { setError(""); try { await api(`/api/doctors/${d.doctor_id}`, token, { method: "PATCH", body: JSON.stringify({ is_active: !d.is_active }) }); await loadDoctors(); await refresh(); } catch (e) { setError((e as Error).message); } }
  async function loadKpis() { setError(""); try { const q = new URLSearchParams({ start_date: dashboardStart, end_date: dashboardEnd }); if (dashboardDepartment) q.set("department", dashboardDepartment); if (dashboardDoctor) q.set("doctor_id", dashboardDoctor); setKpis(await api<Kpis>(`/api/dashboard/kpis?${q.toString()}`, token)); } catch (e) { setError((e as Error).message); } }
  async function openCallNotes(p: Patient) { setNotePatient(p); setError(""); setNoteForm({ status: p.followup_status || "CALLED", call_outcome: "CONTACTED", notes: "", next_followup_date: "", confirmed_surgery_date: p.confirmed_surgery_date || "" }); try { setCallNotes(await api<CallNote[]>(`/api/followups/notes/${p.patient_id}`, token)); } catch (e) { setCallNotes([]); setError((e as Error).message); } }
  async function saveCallNote(e: FormEvent) { e.preventDefault(); if (!notePatient) return; if (noteForm.status === "CONFIRMED_FOR_SURGERY" && !noteForm.confirmed_surgery_date) { setError("Please enter the confirmed surgery date."); return; } setBusy(true); setError(""); try { await api(`/api/followups/notes/${notePatient.patient_id}`, token, { method: "POST", body: JSON.stringify({ ...noteForm, next_followup_date: noteForm.next_followup_date || null, confirmed_surgery_date: noteForm.status === "CONFIRMED_FOR_SURGERY" ? noteForm.confirmed_surgery_date : null }) }); await refresh(); const updatedPatient = (await api<Patient[]>("/api/patients", token)).find(p => p.patient_id === notePatient.patient_id); if (updatedPatient) setNotePatient(updatedPatient); setCallNotes(await api<CallNote[]>(`/api/followups/notes/${notePatient.patient_id}`, token)); setNoteForm(f => ({ ...f, notes: "", call_outcome: "CONTACTED", next_followup_date: "", confirmed_surgery_date: updatedPatient?.confirmed_surgery_date || f.confirmed_surgery_date })); setMessage("Call entry saved; status and history refreshed."); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  const opdPatients = patients.filter(p => p.registration_flow === "OPD_FOLLOWUP" && (!opdDepartmentFilter || p.department === opdDepartmentFilter) && (!opdDoctorFilter || p.doctor_id === opdDoctorFilter));
  const surgeryPatients = patients.filter(p => p.registration_flow === "SURGERY_FOLLOWUP" && (!surgeryDepartmentFilter || p.department === surgeryDepartmentFilter) && (!surgeryDoctorFilter || p.doctor_id === surgeryDoctorFilter));

  if (!token) return <div className="shell login-shell"><main className="login-main"><section className="card login-card"><div className="logo">+</div><h1>Care<span>Plus</span></h1><p className="muted">STAFF PORTAL · POST-DISCHARGE CARE</p><h2>Sign in</h2><p>Use the staff account created by your Care Plus administrator.</p>{error && <div className="error">{error}</div>}<form onSubmit={signIn}><label>Email address<input required type="email" autoComplete="username" value={login.email} onChange={e => setLogin({ ...login, email: e.target.value })} /></label><label>Password<input required type="password" autoComplete="current-password" value={login.password} onChange={e => setLogin({ ...login, password: e.target.value })} /></label><button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button></form></section></main></div>;

  return <div className="shell">
    <aside><div className="logo">+</div><h2>Care<span>Plus</span></h2><p className="muted">POST-DISCHARGE CARE</p>
      <nav>
        <div className="nav-section-title">OVERVIEW</div>
        {[
          ["dashboard", "Dashboard"],
          ["doctorview", "Doctor's Review"],
        ].map(([v, l]) => (
            <button
                key={v}
                className={tab === v ? "nav active" : "nav"}
                onClick={() => {
                  setTab(v);
                  if (v === "dashboard") loadKpis();
                  if (v === "doctorview") {
                    loadDoctors().catch(e => setError(e.message));
                    loadWhatsAppProgress().catch(e => setError(e.message));
                  }
                }}
            >
              {l}
            </button>
        ))}

        <div className="nav-section-title">PATIENT MANAGEMENT</div>
        {[
          ["patients", "Patients"],
          ["episodes", "Create Care Plan"],
          ["tasks", "Reminder Tasks"],
          ["journey", "Patient Journey"],
        ].map(([v, l]) => (
            <button
                key={v}
                className={tab === v ? "nav active" : "nav"}
                onClick={() => {
                  setTab(v);
                  if (v === "journey") {
                    loadPatientJourney().catch(e => setError(e.message));
                  }
                }}
            >
              {l}
            </button>
        ))}

        <div className="nav-section-title">FOLLOW-UP CARE</div>
        {[
          ["opd", "OPD Follow-ups"],
          ["surgery", "Pre-Surgery Follow-ups"],
        ].map(([v, l]) => (
            <button
                key={v}
                className={tab === v ? "nav active" : "nav"}
                onClick={() => setTab(v)}
            >
              {l}
            </button>
        ))}

        <div className="nav-section-title">MONITORING</div>
        {[
          ["progress", "WhatsApp Communication"],
        ].map(([v, l]) => (
            <button
                key={v}
                className={tab === v ? "nav active" : "nav"}
                onClick={() => {
                  setTab(v);
                  loadDoctors().catch(e => setError(e.message));
                  loadWhatsAppProgress().catch(e => setError(e.message));
                }}
            >
              {l}
            </button>
        ))}

        <div className="nav-section-title">ADMINISTRATION</div>
        {[
          ["doctors", "Doctor Management"],
        ].map(([v, l]) => (
            <button
                key={v}
                className={tab === v ? "nav active" : "nav"}
                onClick={() => {
                  setTab(v);
                  loadDoctors().catch(e => setError(e.message));
                }}
            >
              {l}
            </button>
        ))}
      </nav>
      <div className="sidebar-foot"><small>{user?.full_name || user?.email}</small><button className="nav" onClick={signOut}>Sign out</button></div></aside>
    <main className="main">
      <header><div><p className="eyebrow">CARE MANAGEMENT / MVP</p><h1>{(({ dashboard: "Hospital dashboard", doctorview: "Doctor's Review", patients: "Patients", episodes: "Create Care Plan", tasks: "Reminder Tasks", doctors: "Doctor Management", opd: "OPD Follow-ups", surgery: "Pre-Surgery Follow-ups", progress: "WhatsApp Communication", journey: "Patient Journey" }) as Record<string, string>)[tab] || "Care Plus"}</h1><p className="muted">Signed in as {user?.role || "staff"}</p></div>{tab === "dashboard" && <button className="secondary" onClick={preview}>Preview due alerts</button>}</header>
      {selectedPatient ? <section className="patient-context"><div><small>ACTIVE PATIENT</small><strong>{selectedPatient.patient_ref} · {selectedPatient.full_name}</strong><span>{selectedPatient.mobile_number}{selectedPatient.date_of_birth ? ` · DOB ${selectedPatient.date_of_birth}` : ""}{selectedPatient.gender ? ` · ${selectedPatient.gender}` : ""}</span><span>{selectedPatient.registration_flow === "DISCHARGE" ? "Post-hospitalisation care" : selectedPatient.registration_flow === "OPD_FOLLOWUP" ? `OPD follow-up: ${selectedPatient.visit_date || "date not set"}` : `Surgery follow-up: ${selectedPatient.surgery_date || "date not set"}`}</span></div><button className="secondary" onClick={() => { setSelectedPatientId(""); setSelectedEpisodeId(""); setTab("patients"); }}>Change patient</button></section> : <section className="patient-context empty-context"><div><small>NO PATIENT SELECTED</small><strong>Select or register a patient to begin</strong><span>Episodes and tasks will be shown for the selected patient only.</span></div><button className="secondary" onClick={() => setTab("patients")}>Find patient</button></section>}
      {message && <div className="message">{message}<button onClick={() => setMessage("")}>×</button></div>}{error && <div className="error">{error}</div>}
      {tab === "dashboard" && <section className="stats"><div><small>Total patients</small><strong>{patients.length}</strong></div><div><small>Active patient visits</small><strong>{selectedPatient ? patientEpisodes.length : "—"}</strong></div><div><small>Active Reminder Tasks</small><strong>{selectedPatient ? patientTasks.length : "—"}</strong></div></section>}

      {tab === "journey" && <section className="card journey-card">
        <div className="journey-heading"><div><h2>Patient Journey</h2><p className="helper">A chronological, read-only view of this patient's recorded care and communication history.</p></div><button type="button" className="secondary" disabled={!selectedPatientId || journeyLoading} onClick={() => loadPatientJourney().catch(e => setError((e as Error).message))}>{journeyLoading ? "Refreshing…" : "Refresh timeline"}</button></div>
        {!selectedPatient ? <div className="empty-state"><h3>Select a patient first</h3><p>Use “Find / register patient” and select a patient to view their journey.</p><button type="button" onClick={() => setTab("patients")}>Find patient</button></div> : <>
          <div className="journey-patient"><div><small>PATIENT</small><strong>{selectedPatient.patient_ref} · {selectedPatient.full_name}</strong><span>{selectedPatient.registration_flow.replaceAll("_", " ")} · {selectedPatient.mobile_number}</span></div><div className="journey-count"><strong>{journey?.total_events ?? 0}</strong><span>recorded events</span></div></div>
          <div className="journey-toolbar"><label>Show activity<select value={journeyFilter} onChange={e => setJourneyFilter(e.target.value)}><option value="all">All activity</option><option value="whatsapp">WhatsApp</option><option value="care">Care and episodes</option><option value="followups">Follow-up calls</option><option value="alerts">Reminder previews</option></select></label></div>
          {journeyLoading && <p className="helper">Loading patient history…</p>}
          {!journeyLoading && journey && <div className="journey-timeline">{journey.events.filter(ev => journeyFilter === "all" || ev.category === journeyFilter).map(ev => <article className="journey-event" key={ev.id}><div className={`journey-dot journey-${ev.category}`} /><div className="journey-event-content"><div className="journey-event-top"><div><span className={`journey-category journey-${ev.category}`}>{({ care: "CARE", whatsapp: "WHATSAPP", followups: "FOLLOW-UP", alerts: "ALERT" })[ev.category]}</span><h3>{ev.title}</h3></div><time>{ev.occurred_at ? new Date(ev.occurred_at).toLocaleString() : "Date not recorded"}</time></div>{ev.description && <p className={ev.kind === "whatsapp" ? "journey-message" : ""}>{ev.description}</p>}{ev.status && <span className="journey-status">{ev.status.replaceAll("_", " ")}</span>}{Object.entries(ev.details || {}).filter(([key, value]) => value !== null && value !== "" && value !== undefined && key !== "provider_message_id" && key !== "phone_number" && key !== "staff_user_id" && key !== "message_event_id").map(([key, value]) => <div className="journey-detail" key={key}><span>{key.replaceAll("_", " ")}</span><strong>{Array.isArray(value) ? value.join(", ") : String(value)}</strong></div>)}</div></article>)}{!journey.events.filter(ev => journeyFilter === "all" || ev.category === journeyFilter).length && <div className="empty-state"><p>No activity in this category has been recorded for this patient.</p></div>}</div>}
          <section className="whatsapp-image-gallery">
            <h3>WhatsApp images for this patient</h3>
            {whatsappMedia.filter(m => m.patient_id === selectedPatientId).length === 0
                ? <p className="helper">No stored WhatsApp images are available for this patient.</p>
                : <div className="whatsapp-image-grid">
                  {whatsappMedia.filter(m => m.patient_id === selectedPatientId).map(media => (
                      <article className="whatsapp-image-card" key={media.media_record_id}>
                        <a href={media.url} target="_blank" rel="noreferrer">
                          <img src={media.url} alt={media.caption || "WhatsApp image"} loading="lazy" />
                        </a>
                        {media.caption && <p>{media.caption}</p>}
                        <small>{media.created_at ? new Date(media.created_at).toLocaleString() : "Date not recorded"}</small>
                        <small>Image links expire after {media.url_expires_in} seconds.</small>
                      </article>
                  ))}
                </div>}
          </section>
          <p className="helper journey-privacy">This timeline displays records already stored in Care Plus. Reminder entries are previews only; this page does not send messages or change clinical records. WhatsApp messages appear only when linked to this patient's ID.</p>
        </>}
      </section>}
      {tab === "doctorview" && <section className="card"><h2>Doctor patient progress overview</h2><p className="helper">A working overview of inbound patient replies, messages needing staff review, and follow-up flags. This view does not make clinical decisions; staff and doctors should review the original message and patient context.</p><div className="two"><label>Department<select value={whatsappDepartment} onChange={e => { setWhatsappDepartment(e.target.value); setWhatsappDoctor(""); }}><option value="">All departments</option>{departments.map(d => <option key={d}>{d}</option>)}</select></label><label>Doctor<select value={whatsappDoctor} onChange={e => setWhatsappDoctor(e.target.value)}><option value="">All doctors</option>{managedDoctors.filter(d => d.is_active !== false && (!whatsappDepartment || d.department === whatsappDepartment)).map(d => <option key={d.doctor_id} value={d.doctor_id}>{d.full_name}</option>)}</select></label></div><button type="button" className="secondary" onClick={() => loadWhatsAppProgress().catch(e => setError(e.message))}>Refresh patient progress</button><div className="stats kpi-grid"><div><small>Inbound replies</small><strong>{whatsappEvents.filter(w => w.direction === "INBOUND").length}</strong></div><div><small>Assigned to patient</small><strong>{whatsappEvents.filter(w => w.direction === "INBOUND" && !!w.patient_id).length}</strong></div><div><small>Needs review</small><strong>{whatsappEvents.filter(w => w.needs_review).length}</strong></div><div><small>Flagged for follow-up</small><strong>{whatsappEvents.filter(w => w.attention_flag).length}</strong></div></div><h3>Latest patient replies</h3><div className="table-scroll"><table><thead><tr><th>Date / time</th><th>Patient</th><th>Episode / department</th><th>Latest reply</th><th>Follow-up</th></tr></thead><tbody>{whatsappEvents.filter(w => w.direction === "INBOUND" && !!w.episode_id).slice().sort((a,b) => (b.received_at || "").localeCompare(a.received_at || "")).slice(0,100).map(w => <tr key={w.event_id}><td>{w.received_at ? new Date(w.received_at).toLocaleString() : "—"}</td><td>{w.patient_name || "Unmatched patient"}<small>{w.patient_ref || w.phone_number}</small></td><td>{w.episode_ref || "—"}<small>{w.department || "—"}</small></td><td>{w.message_text}
        {whatsappMedia.filter(m => m.event_id === w.event_id).map(media => (
            <div className="whatsapp-message-image" key={media.media_record_id}>
              <a href={media.url} target="_blank" rel="noreferrer">
                <img src={media.url} alt={media.caption || "WhatsApp attachment"} loading="lazy" />
              </a>
              {media.caption && <small>{media.caption}</small>}
            </div>
        ))}
      </td><td>{w.needs_review ? <strong>Needs review</strong> : w.attention_flag ? <strong className="attention-label">Flagged</strong> : "No flag"}{w.attention_note && <small>{w.attention_note}</small>}<textarea rows={2} placeholder="Doctor comment to patient" value={doctorComments[w.event_id] || ""} onChange={e => setDoctorComments(current => ({ ...current, [w.event_id]: e.target.value }))} /><button type="button" className="small-button" disabled={busy || !w.patient_id || !w.episode_id || !(doctorComments[w.event_id] || "").trim()} onClick={() => sendDoctorComment(w)}>Send comment on WhatsApp</button></td></tr>)}{!whatsappEvents.some(w => w.direction === "INBOUND" && !!w.episode_id) && <tr><td colSpan={5}>No inbound patient replies found for the selected filters.</td></tr>}</tbody></table></div><p className="helper">This overview shows up to the latest 500 WhatsApp events returned by the API. Use WhatsApp progress to assign unmatched messages or update follow-up flags.</p></section>}
      {tab === "progress" && <section className="card"><h2>WhatsApp conversation and patient progress</h2><p className="helper">Incoming replies are linked automatically only when a unique patient and a unique active visit can be identified. Ambiguous messages remain unassigned until staff review them.</p><div className="two"><label>Department filter<select value={whatsappDepartment} onChange={e => { setWhatsappDepartment(e.target.value); setWhatsappDoctor(""); }}><option value="">All departments</option>{departments.map(d => <option key={d}>{d}</option>)}</select></label><label>Doctor filter<select value={whatsappDoctor} onChange={e => setWhatsappDoctor(e.target.value)}><option value="">All doctors</option>{managedDoctors.filter(d => d.is_active !== false && (!whatsappDepartment || d.department === whatsappDepartment)).map(d => <option key={d.doctor_id} value={d.doctor_id}>{d.full_name}</option>)}</select></label></div><div className="two"><label>Follow-up filter<select value={whatsappAttentionFilter} onChange={e => setWhatsappAttentionFilter(e.target.value)}><option value="ALL">All messages</option><option value="FLAGGED">Flagged for follow-up</option><option value="UNFLAGGED">Not flagged</option></select></label><div><span className="helper">Showing up to the latest 500 events</span><button type="button" className="secondary" onClick={() => loadWhatsAppProgress().catch(e => setError(e.message))}>Refresh messages</button></div></div><div className="table-scroll"><table><thead><tr><th>Date / time</th><th>Direction</th><th>Patient</th><th>Episode / department</th><th>Message</th><th>Status / action</th></tr></thead><tbody>{whatsappEvents.filter(w => !!w.episode_id && (whatsappAttentionFilter === "ALL" || (whatsappAttentionFilter === "FLAGGED" ? w.attention_flag : !w.attention_flag))).map(w => <tr key={w.event_id}><td>{w.received_at ? new Date(w.received_at).toLocaleString() : "—"}</td><td>{w.direction}</td><td>{w.patient_name ? <>{w.patient_name}<small>{w.patient_ref}</small></> : <>{w.phone_number}<small>Unmatched patient</small></>}</td><td>{w.episode_ref || "—"}<small>{w.department || "—"}</small></td><td>{w.message_text}
        {whatsappMedia.filter(m => m.event_id === w.event_id).map(media => (
            <div className="whatsapp-message-image" key={media.media_record_id}>
              <a href={media.url} target="_blank" rel="noreferrer">
                <img src={media.url} alt={media.caption || "WhatsApp attachment"} loading="lazy" />
              </a>
              {media.caption && <small>{media.caption}</small>}
            </div>
        ))}
      </td><td>{w.needs_review ? <><strong>Needs review</strong><div><button type="button" className="small-button" onClick={() => { setAssigningWhatsAppEvent(assigningWhatsAppEvent === w.event_id ? "" : w.event_id); setWhatsappAssignments(a => ({ ...a, [w.event_id]: a[w.event_id] || { patient_id: "", episode_id: "" } })); }}>{assigningWhatsAppEvent === w.event_id ? "Cancel" : "Review / assign"}</button></div>{assigningWhatsAppEvent === w.event_id && <div className="assignment-controls"><label>Patient<select value={whatsappAssignments[w.event_id]?.patient_id || ""} onChange={e => setWhatsappAssignments(a => ({ ...a, [w.event_id]: { patient_id: e.target.value, episode_id: "" } }))}><option value="">Select patient…</option>{patients.map(p => <option key={p.patient_id} value={p.patient_id}>{p.patient_ref} — {p.full_name}</option>)}</select></label><label>Visit (optional)<select value={whatsappAssignments[w.event_id]?.episode_id || ""} onChange={e => setWhatsappAssignments(a => ({ ...a, [w.event_id]: { ...(a[w.event_id] || { patient_id: "" }), episode_id: e.target.value } }))}><option value="">No episode selected</option>{episodes.filter(ep => ep.patient_id === whatsappAssignments[w.event_id]?.patient_id).map(ep => <option key={ep.episode_id} value={ep.episode_id}>{ep.episode_ref} — {ep.department} ({ep.status})</option>)}</select></label><button type="button" disabled={busy || !whatsappAssignments[w.event_id]?.patient_id} onClick={() => assignWhatsAppMessage(w.event_id)}>{busy ? "Saving…" : "Save assignment"}</button><p className="helper">Choose the patient after verifying the sender. An episode can only be assigned to that same patient.</p></div>}</> : w.status}{w.direction === "INBOUND" && <div className="attention-controls">{w.attention_flag && <><strong className="attention-label">Flagged for follow-up</strong>{w.attention_note && <small>Staff note: {w.attention_note}</small>}</>}<button type="button" className="small-button" onClick={() => updateWhatsAppAttention(w).catch(e => setError((e as Error).message))}>{w.attention_flag ? "Resolve flag" : "Flag for follow-up"}</button></div>}</td></tr>)}{!whatsappEvents.filter(w => !!w.episode_id && (whatsappAttentionFilter === "ALL" || (whatsappAttentionFilter === "FLAGGED" ? w.attention_flag : !w.attention_flag))).length && <tr><td colSpan={6}>{whatsappEvents.length ? "No messages match this follow-up filter." : "No WhatsApp events yet. Configure the WhatsApp Cloud API and webhook to receive real messages."}</td></tr>}</tbody></table></div><p className="helper">Do not use WhatsApp messages as a substitute for emergency services or clinical assessment. Patient consent, privacy notices, access controls, retention, and approved message templates must be configured before production use.</p></section>}

      {tab === "patients" && <div className="page-grid"><section className="card"><h2>Register patient</h2><p className="helper">After saving, Care Plus automatically opens the visit form for this patient.</p><form autoComplete="off" onSubmit={submitPatient}>
        <label>Care pathway *<select required value={pf.registration_flow} onChange={e => setPf({ ...pf, registration_flow: e.target.value as typeof pf.registration_flow, visit_date: "", surgery_date: "", department: "", doctor_id: "" })}><option value="DISCHARGE">Discharge — post-hospitalisation care</option><option value="OPD_FOLLOWUP">OPD follow-up</option><option value="SURGERY_FOLLOWUP">Surgery follow-up</option></select></label>
        <p className="helper">{pf.registration_flow === "DISCHARGE" ? "Continue to the existing visit and home-Reminder Task workflow after registration." : pf.registration_flow === "OPD_FOLLOWUP" ? "No admission or discharge episode is required. A reminder preview is due one day before the OPD visit." : "No admission or discharge episode is required. A reminder preview is due one day before surgery."}</p>
        <label>Full name *<input required autoComplete="off" value={pf.full_name} onChange={e => setPf({ ...pf, full_name: e.target.value })} /></label>
        <label>Mobile number *<input required type="tel" inputMode="numeric" pattern="[6-9][0-9]{9}" minLength={10} maxLength={10} autoComplete="off" placeholder="10-digit mobile number" value={pf.mobile_number} onChange={e => setPf({ ...pf, mobile_number: e.target.value.replace(/\D/g, "").slice(0, 10) })} /></label>
        <div className="two"><label>Date of birth<input type="date" value={pf.date_of_birth} onChange={e => setPf({ ...pf, date_of_birth: e.target.value })} /></label><label>Gender<select value={pf.gender} onChange={e => setPf({ ...pf, gender: e.target.value })}><option value="">Not specified</option><option>Female</option><option>Male</option><option>Other</option><option>Prefer not to say</option></select></label></div>
        <label>Email<input type="email" autoComplete="off" value={pf.email} onChange={e => setPf({ ...pf, email: e.target.value })} /></label>
        <label>Address<textarea rows={2} autoComplete="off" value={pf.address} onChange={e => setPf({ ...pf, address: e.target.value })} /></label>
        {pf.registration_flow === "OPD_FOLLOWUP" && <label>OPD follow-up / visit date *<input required type="date" min={today} value={pf.visit_date} onChange={e => setPf({ ...pf, visit_date: e.target.value })} /></label>}
        {pf.registration_flow === "SURGERY_FOLLOWUP" && <label>Surgery date *<input required type="date" min={today} value={pf.surgery_date} onChange={e => setPf({ ...pf, surgery_date: e.target.value })} /></label>}
        {pf.registration_flow !== "DISCHARGE" && <>
          <label>Source *<select required value={pf.source} onChange={e => setPf({ ...pf, source: e.target.value })}>{["Walk In", "Camp", "Reference", "Online", "Existing Patient", "Other"].map(v => <option key={v}>{v}</option>)}</select></label>
          <label>Department *<select required value={pf.department} onChange={e => setPf({ ...pf, department: e.target.value, doctor_id: "" })}><option value="">Select department</option>{departments.filter(d => d !== "Other").map(d => <option key={d} value={d}>{d}</option>)}</select></label>
          <label>Doctor *<select required value={pf.doctor_id} disabled={!pf.department || doctors.length === 0} onChange={e => setPf({ ...pf, doctor_id: e.target.value })}><option value="">{!pf.department ? "Select department first" : doctors.length ? "Select doctor" : "No active doctors configured for this department"}</option>{doctors.map(d => <option key={d.doctor_id} value={d.doctor_id}>{d.full_name}</option>)}</select></label>
          {pf.department && doctors.length === 0 && <small className="helper">No doctors are configured for {pf.department}. Add doctors to the doctors table in PostgreSQL, then reload this form.</small>}
        </>}
        <button disabled={busy}>{busy ? "Saving…" : pf.registration_flow === "DISCHARGE" ? "Register patient and continue" : "Register patient and schedule reminder"}</button>
        <small>Each patient has a unique ID; shared mobile numbers are allowed.</small>
      </form></section>
        <section className="card"><div className="card-head"><h2>Search / select patient</h2><input aria-label="Search patients" placeholder="Name, patient ID or mobile" value={search} onChange={e => setSearch(e.target.value)} /></div><p className="helper">Select a patient to open their visits. All subsequent entries will stay in that patient's context.</p><div className="table-scroll"><table><thead><tr><th>Patient</th><th>Patient ref</th><th>Mobile</th><th>Flow / appointment</th><th>Status</th><th></th></tr></thead><tbody>{visiblePatients.map(p => <tr key={p.patient_id} className={p.patient_id === selectedPatientId ? "selected-row" : ""}><td>{p.full_name}</td><td>{p.patient_ref}</td><td>{p.mobile_number}</td><td>{p.registration_flow === "DISCHARGE" ? "Discharge" : p.registration_flow === "OPD_FOLLOWUP" ? `OPD: ${p.visit_date || "—"} · ${p.department || "—"} · ${p.doctor_name || "—"}` : `Surgery: ${p.surgery_date || "—"} · ${p.department || "—"} · ${p.doctor_name || "—"}`}</td><td>{p.status}</td><td><button className="small-button" onClick={() => selectPatient(p, "episodes")}>{p.patient_id === selectedPatientId ? "Selected" : "Select patient"}</button> <button type="button" className="small-button danger-button" onClick={() => deleteRecord(`/api/patients/${p.patient_id}`, "patient")}>Delete</button></td></tr>)}{!visiblePatients.length && <tr><td colSpan={6}>No matching patients.</td></tr>}</tbody></table></div></section></div>}

      {tab === "dashboard" && <section className="card"><h2>Hospital KPIs</h2><div className="two"><label>From date<input type="date" value={dashboardStart} onChange={e => setDashboardStart(e.target.value)} /></label><label>To date<input type="date" value={dashboardEnd} onChange={e => setDashboardEnd(e.target.value)} /></label></div><div className="two"><label>Department<select value={dashboardDepartment} onChange={e => { setDashboardDepartment(e.target.value); setDashboardDoctor(""); }}><option value="">All departments</option>{departments.filter(d => d !== "Other").map(d => <option key={d}>{d}</option>)}</select></label><label>Doctor<select value={dashboardDoctor} onChange={e => setDashboardDoctor(e.target.value)}><option value="">All doctors</option>{managedDoctors.filter(d => d.is_active !== false && (!dashboardDepartment || d.department === dashboardDepartment)).map(d => <option key={d.doctor_id} value={d.doctor_id}>{d.full_name} — {d.department}</option>)}</select></label></div><button onClick={loadKpis}>Apply filters</button>{kpis && <div className="stats kpi-grid">{[["New patients",kpis.total_new_patients],["OPD planned",kpis.opd_planned],["OPD attended",kpis.opd_attended],["OPD pending",kpis.opd_pending],["Surgery planned",kpis.surgery_planned],["Surgery confirmed",kpis.surgery_confirmed],["Surgery refused",kpis.surgery_refused],["Active post-discharge episodes",kpis.post_discharge_active_episodes]].map(([label,value]) => <div key={label}><small>{label}</small><strong>{value}</strong></div>)}</div>}<p className="helper">OPD attended counts follow-ups marked ATTENDED. Use the OPD follow-up list to update attendance status. KPIs use appointment date for OPD and surgery; active post-discharge episodes are those overlapping the selected period.</p></section>}

      {tab === "doctors" && <div className="page-grid"><section className="card"><h2>Add doctor</h2><form onSubmit={createDoctor}><label>Doctor full name *<input required value={doctorForm.full_name} onChange={e => setDoctorForm({ ...doctorForm, full_name: e.target.value })} /></label><label>Department *<select required value={doctorForm.department} onChange={e => setDoctorForm({ ...doctorForm, department: e.target.value })}>{departments.filter(d => d !== "Other").map(d => <option key={d}>{d}</option>)}</select></label><button disabled={busy}>{busy ? "Saving…" : "Add doctor"}</button></form></section><section className="card"><h2>Configured doctors</h2><div className="table-scroll"><table><thead><tr><th>Name</th><th>Department</th><th>Status</th><th></th></tr></thead><tbody>{managedDoctors.map(d => <tr key={d.doctor_id}><td>{d.full_name}</td><td>{d.department}</td><td>{d.is_active === false ? "Inactive" : "Active"}</td><td><button className="small-button" onClick={() => toggleDoctor(d)}>{d.is_active === false ? "Activate" : "Deactivate"}</button></td></tr>)}{!managedDoctors.length && <tr><td colSpan={4}>No doctors configured yet.</td></tr>}</tbody></table></div></section></div>}

      {tab === "opd" && <section className="card"><h2>OPD follow-up register</h2><div className="two"><label>Filter by department<select value={opdDepartmentFilter} onChange={e => { setOpdDepartmentFilter(e.target.value); setOpdDoctorFilter(""); }}><option value="">All departments</option>{departments.map(d => <option key={d}>{d}</option>)}</select></label><label>Filter by doctor<select value={opdDoctorFilter} onChange={e => setOpdDoctorFilter(e.target.value)}><option value="">All doctors</option>{managedDoctors.filter(d => d.is_active !== false && (!opdDepartmentFilter || d.department === opdDepartmentFilter)).map(d => <option key={d.doctor_id} value={d.doctor_id}>{d.full_name}</option>)}</select></label></div><div className="table-scroll"><table><thead><tr><th>Patient</th><th>Mobile</th><th>Department / doctor</th><th>Visit date</th><th>Source</th><th>Status</th><th>Update</th><th>Actions</th></tr></thead><tbody>{opdPatients.map(p => <tr key={p.patient_id}><td>{p.full_name}<small>{p.patient_ref}</small></td><td>{p.mobile_number}</td><td>{p.department}<small>{p.doctor_name || "—"}</small></td><td>{p.visit_date || "—"}</td><td>{p.source || "—"}</td><td>{p.followup_status || "PLANNED"}</td><td><select value={p.followup_status || "PLANNED"} onChange={async e => { try { await api(`/api/followups/status/${p.patient_id}?status=${e.target.value}`, token, { method: "PATCH" }); await refresh(); } catch (err) { setError((err as Error).message); } }}><option value="PLANNED">Planned</option><option value="ATTENDED">Attended</option><option value="CANCELLED">Cancelled</option></select></td><td><button type="button" className="small-button danger-button" onClick={() => deleteRecord(`/api/followups/${p.patient_id}`, "OPD follow-up")}>Delete</button></td></tr>)}{!opdPatients.length && <tr><td colSpan={8}>No OPD follow-ups match these filters.</td></tr>}</tbody></table></div></section>}

      {tab === "surgery" && <div className="page-grid surgery-page-grid"><section className="card"><h2>Surgery follow-up register</h2><div className="two"><label>Filter by department<select value={surgeryDepartmentFilter} onChange={e => { setSurgeryDepartmentFilter(e.target.value); setSurgeryDoctorFilter(""); }}><option value="">All departments</option>{departments.map(d => <option key={d}>{d}</option>)}</select></label><label>Filter by doctor<select value={surgeryDoctorFilter} onChange={e => setSurgeryDoctorFilter(e.target.value)}><option value="">All doctors</option>{managedDoctors.filter(d => d.is_active !== false && (!surgeryDepartmentFilter || d.department === surgeryDepartmentFilter)).map(d => <option key={d.doctor_id} value={d.doctor_id}>{d.full_name}</option>)}</select></label></div><div className="table-scroll"><table><thead><tr><th>Patient</th><th>Mobile</th><th>Department / doctor</th><th>Planned / confirmed surgery date</th><th>Source</th><th>Status</th><th>Call history</th></tr></thead><tbody>{surgeryPatients.map(p => <tr key={p.patient_id}><td>{p.full_name}<small>{p.patient_ref}</small><button type="button" className="small-button" onClick={() => openCallNotes(p)}>View / add notes</button><button type="button" className="small-button danger-button" onClick={() => deleteRecord(`/api/followups/${p.patient_id}`, "surgery follow-up")}>Delete follow-up</button></td><td>{p.mobile_number}</td><td>{p.department}<small>{p.doctor_name || "—"}</small></td><td>{p.surgery_date || "—"}{p.confirmed_surgery_date && <small>Confirmed: {p.confirmed_surgery_date}</small>}</td><td>{p.source || "—"}</td><td>{(p.followup_status || "PLANNED").replaceAll("_", " ")}</td><td><button className="small-button" onClick={() => openCallNotes(p)}>View / add notes</button></td></tr>)}{!surgeryPatients.length && <tr><td colSpan={7}>No surgery follow-ups match these filters.</td></tr>}</tbody></table></div></section>{notePatient && <section className="card"><h2>Call history: {notePatient.full_name}</h2><form onSubmit={saveCallNote}><label>Call outcome *<select required value={noteForm.call_outcome} onChange={e => setNoteForm({ ...noteForm, call_outcome: e.target.value })}>{[["CONTACTED","Patient contacted"],["NOT_REACHABLE","Not reachable"],["BUSY_CALLBACK","Busy / call back requested"],["WRONG_NUMBER","Wrong number"],["LEFT_MESSAGE","Message left"],["OTHER","Other"]].map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label><label>Updated surgery status *<select required value={noteForm.status} onChange={e => setNoteForm({ ...noteForm, status: e.target.value })}>{[["PLANNED","Planned"],["CALLED","Called"],["CONFIRMED_FOR_SURGERY","Confirmed for surgery"],["REFUSED_FOR_SURGERY","Refused for surgery"],["RESCHEDULE_REQUESTED","Reschedule requested"],["NOT_REACHABLE","Not reachable"],["COMPLETED","Completed"]].map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label>{noteForm.status === "CONFIRMED_FOR_SURGERY" && <label>Confirmed surgery date *<input required type="date" min={today} value={noteForm.confirmed_surgery_date} onChange={e => setNoteForm({ ...noteForm, confirmed_surgery_date: e.target.value })} /></label>}<label>Next call / follow-up date (optional)<input type="date" min={today} value={noteForm.next_followup_date} onChange={e => setNoteForm({ ...noteForm, next_followup_date: e.target.value })} /></label><label>Call notes *<textarea required rows={4} value={noteForm.notes} onChange={e => setNoteForm({ ...noteForm, notes: e.target.value })} placeholder="Record what the patient said, concerns, agreed date, next action…" /></label><button disabled={busy}>{busy ? "Saving…" : "Save call entry"}</button></form><p className="helper">Original planned date: {notePatient.surgery_date || "—"} · Confirmed date: {notePatient.confirmed_surgery_date || "Not confirmed"}</p><h3>Previous notes</h3><div className="table-scroll"><table><thead><tr><th>Date / time</th><th>Call outcome</th><th>Status</th><th>Confirmed surgery date</th><th>Next follow-up</th><th>Notes</th></tr></thead><tbody>{callNotes.map(n => <tr key={n.note_id}><td>{new Date(n.called_at).toLocaleString()}</td><td>{(n.call_outcome || "CONTACTED").replaceAll("_", " ")}</td><td>{n.status.replaceAll("_", " ")}</td><td>{n.confirmed_surgery_date || "—"}</td><td>{n.next_followup_date || "—"}</td><td>{n.notes}</td></tr>)}{!callNotes.length && <tr><td colSpan={6}>No call notes yet.</td></tr>}</tbody></table></div></section>}</div>}

      {tab === "episodes" && <div className="page-grid"><section className="card"><h2>Create Care Plan</h2>{!selectedPatient && <div className="error">Select a patient first. You can find a patient from the first page.</div>}<p className="helper">The episode will be attached to the active patient shown above.</p><form autoComplete="off" onSubmit={submitEpisode}><label>Patient *<select required value={selectedPatientId || ef.patient_id} onChange={e => { setSelectedPatientId(e.target.value); setEf({ ...ef, patient_id: e.target.value }); }}><option value="">Select patient</option>{patients.map(p => <option key={p.patient_id} value={p.patient_id}>{p.patient_ref} — {p.full_name}</option>)}</select></label><label>Department *<select required value={ef.department} onChange={e => setEf({ ...ef, department: e.target.value, doctor_id: "", treating_doctor: "" })}>{departments.map(d => <option key={d}>{d}</option>)}</select></label><label>Treating doctor<select value={ef.doctor_id} onChange={e => { const d = managedDoctors.find(x => x.doctor_id === e.target.value); setEf({ ...ef, doctor_id: e.target.value, treating_doctor: d?.full_name || "" }); }}><option value="">Select doctor (optional)</option>{managedDoctors.filter(d => d.is_active !== false && d.department === ef.department).map(d => <option key={d.doctor_id} value={d.doctor_id}>{d.full_name}</option>)}</select></label><div className="two"><label>Admission date<input type="date" max={ef.discharge_date || undefined} value={ef.admission_date} onChange={e => setEf({ ...ef, admission_date: e.target.value })} /></label><label>Discharge date *<input required type="date" min={ef.admission_date || undefined} value={ef.discharge_date} onChange={e => setEf({ ...ef, discharge_date: e.target.value })} /></label></div><div className="two"><label>Care starts *<input required type="date" min={ef.discharge_date || undefined} value={ef.care_start_date} onChange={e => setEf({ ...ef, care_start_date: e.target.value })} /></label><label>Care ends *<input required type="date" min={ef.care_start_date} value={ef.care_end_date} onChange={e => setEf({ ...ef, care_end_date: e.target.value })} /></label></div><label>Reason / care notes<textarea rows={3} value={ef.reason_for_care} onChange={e => setEf({ ...ef, reason_for_care: e.target.value })} /></label><button disabled={busy || !selectedPatientId}>{busy ? "Creating…" : "Create Care Plan and continue"}</button></form></section>
        <section className="card"><h2>{selectedPatient ? `Visits for ${selectedPatient.full_name}` : "Select a patient to view episodes"}</h2><div className="table-scroll"><table><thead><tr><th>Episode</th><th>Department / doctor</th><th>Care period</th><th>Status</th><th>Actions</th></tr></thead><tbody>{patientEpisodes.map(ep => <tr key={ep.episode_id} className={ep.episode_id === selectedEpisodeId ? "selected-row" : ""}><td>{ep.episode_ref}</td><td>{ep.department}<small>{ep.treating_doctor || "Doctor not set"}</small></td><td>{ep.care_start_date} → {ep.care_end_date}</td><td>{ep.status}</td><td><button className="small-button" onClick={() => { setSelectedEpisodeId(ep.episode_id); setTf(f => ({ ...f, episode_id: ep.episode_id })); setTab("tasks"); }}>{ep.episode_id === selectedEpisodeId ? "Selected" : "Add Reminder Task"}</button> <button type="button" className="small-button danger-button" onClick={() => deleteRecord(`/api/episodes/${ep.episode_id}`, "visit")}>Delete</button></td></tr>)}{!patientEpisodes.length && <tr><td colSpan={5}>{selectedPatient ? "No visits for this patient yet." : "Select a patient first."}</td></tr>}</tbody></table></div></section></div>}

      {tab === "tasks" && <div className="page-grid"><section className="card"><h2>Add Reminder Task</h2>{!selectedPatient && <div className="error">Select a patient first.</div>}<p className="helper">Only visits belonging to the active patient are available here.</p><form autoComplete="off" onSubmit={submitTask}><label>Visit *<select required value={tf.episode_id} onChange={e => setTf({ ...tf, episode_id: e.target.value })}><option value="">Select episode</option>{patientEpisodes.map(ep => <option key={ep.episode_id} value={ep.episode_id}>{ep.episode_ref} — {ep.department}</option>)}</select></label><label>Task type<select value={tf.task_type} onChange={e => setTf({ ...tf, task_type: e.target.value })}>{taskTypes.map(t => <option key={t}>{t}</option>)}</select></label><label>Task title *<input required value={tf.title} onChange={e => setTf({ ...tf, title: e.target.value })} /></label><label>Instructions<textarea rows={3} value={tf.instructions} onChange={e => setTf({ ...tf, instructions: e.target.value })} /></label><div className="two"><label>Start date *<input required type="date" min={episodes.find(ep => ep.episode_id === tf.episode_id)?.care_start_date} max={episodes.find(ep => ep.episode_id === tf.episode_id)?.care_end_date} value={tf.start_date} onChange={e => setTf({ ...tf, start_date: e.target.value, end_date: tf.end_date < e.target.value ? e.target.value : tf.end_date })} /></label><label>End date *<input required type="date" min={tf.start_date} max={episodes.find(ep => ep.episode_id === tf.episode_id)?.care_end_date} value={tf.end_date} onChange={e => setTf({ ...tf, end_date: e.target.value })} /></label></div><fieldset><legend>Reminder times *</legend><p className="muted">A preview is generated for each selected slot on every day in this date range.</p>{slots.map(s => <label className="check-row" key={s.value}><input type="checkbox" checked={tf.selected_slots.includes(s.value)} onChange={e => setTf(f => ({ ...f, selected_slots: e.target.checked ? [...f.selected_slots, s.value] : f.selected_slots.filter(x => x !== s.value) }))} /><span>{s.label}<small>{s.time}</small></span></label>)}</fieldset><button disabled={busy || !selectedPatientId || !patientEpisodes.length || !tf.episode_id || !tf.selected_slots.length}>{busy ? "Saving…" : "Add Reminder Task"}</button></form></section>
        <section className="card"><h2>{selectedPatient ? `Reminder Tasks for ${selectedPatient.full_name}` : "Select a patient to view tasks"}</h2><div className="table-scroll"><table><thead><tr><th>Task</th><th>Type</th><th>Date range</th><th>Reminder slots</th><th>Episode</th><th>Status</th><th>Actions</th></tr></thead><tbody>{patientTasks.map(t => <tr key={t.task_id}><td>{t.title}<small>{t.instructions || ""}</small></td><td>{t.task_type}</td><td>{t.start_date} → {t.end_date}</td><td>{(t.selected_slots || []).map(s => slots.find(x => x.value === s)?.label || s).join(", ")}</td><td>{patientEpisodes.find(ep => ep.episode_id === t.episode_id)?.episode_ref || t.episode_id.slice(0, 8)}</td><td>{t.status}</td><td><button type="button" className="small-button danger-button" onClick={() => deleteRecord(`/api/tasks/${t.task_id}`, "Reminder Task")}>Delete</button></td></tr>)}{!patientTasks.length && <tr><td colSpan={7}>{selectedPatient ? "No Reminder Reminder Tasks for this patient yet." : "Select a patient first."}</td></tr>}</tbody></table></div></section></div>}
      <footer>Care Plus MVP · Local development · Reminder previews are logs only and do not send SMS, WhatsApp, or calls</footer>
    </main>
  </div>;
}
