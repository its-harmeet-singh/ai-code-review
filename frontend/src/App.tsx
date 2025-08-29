import { useEffect, useState } from "react";
import {
  ping,
  whoAmI,
  createProject,
  createJob,
  uploadZip,
  getJob,
  listProjects,
  listJobs,
  importGithub,
  getProjectFile,
} from "./lib/api";
import { useAuth } from "./lib/auth";
import { signInWithPopup, signOut } from "firebase/auth";
import { auth, googleProvider, githubProvider } from "./lib/firebase";

export default function App() {
  const { user, loading } = useAuth();

  const [api, setApi] = useState<any>(null);
  const [me, setMe] = useState<any>(null);

  // analysis job UI state
  const [jobStatus, setJobStatus] = useState<string>("—");
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobResults, setJobResults] = useState<any>(null);
  const [jobError, setJobError] = useState<string | null>(null);

  // dashboard state
  const [projects, setProjects] = useState<any[]>([]);
  const [jobs, setJobs] = useState<any[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | "all">("all");

  // GitHub import state
  const [ghUrl, setGhUrl] = useState<string>("");
  const [ghBranch, setGhBranch] = useState<string>("main");

  // vpoints viewer state
  const [selectedV, setSelectedV] = useState<any | null>(null);
  const [sourceView, setSourceView] = useState<{ path: string; content: string } | null>(null);

  useEffect(() => {
    ping().then(setApi).catch((e) => setApi({ error: true, msg: String(e) }));
  }, []);

  useEffect(() => {
    if (user) refreshDashboard();
  }, [user]);

  async function refreshDashboard() {
    try {
      const p = await listProjects(50);
      setProjects(p.items || []);
      const j = await listJobs({ limit: 50 });
      setJobs(j.items || []);
    } catch (e) {
      console.error(e);
    }
  }

  async function loadMe() {
    try {
      const res = await whoAmI();
      setMe(res);
    } catch (e: any) {
      setMe({ error: String(e) });
    }
  }

  async function runAnalysis() {
    setJobResults(null);
    setJobError(null);
    setJobId(null);
    setSelectedV(null);
    setSourceView(null);
    setJobStatus("starting…");

    try {
      // 1) Create a project doc
      const project = await createProject("Uploaded Repo", "upload");
      setJobStatus("project created");

      // 2) Ask for a .zip file
      const input = document.createElement("input");
      input.type = "file";
      input.accept = ".zip";
      input.onchange = async () => {
        try {
          const file = input.files?.[0];
          if (!file) {
            setJobStatus("no file selected");
            return;
          }

          setJobStatus("uploading zip…");
          await uploadZip(project.id, file);

          // 3) Create a job
          setJobStatus("creating job…");
          const j = await createJob(project.id);
          setJobId(j.id);
          setJobStatus("pending");

          // 4) Poll until done/error
          async function poll() {
            try {
              const data = await getJob(j.id);
              setJobStatus(data.status);
              if (data.status === "done" || data.status === "error") {
                const r = data.results ?? null;
                if (r && !r.projectId) r.projectId = project.id; // ensure viewer can fetch files
                setJobResults(r);
                if (data.status === "error") setJobError(data.error ?? "Job failed");
                refreshDashboard(); // show the new job in dashboard
              } else {
                setTimeout(poll, 1500);
              }
            } catch (e: any) {
              setJobStatus("poll error");
              setJobError(String(e));
            }
          }
          poll();
        } catch (e: any) {
          setJobStatus("upload/job error");
          setJobError(String(e));
        }
      };
      input.click();
    } catch (e: any) {
      setJobStatus("project error");
      setJobError(String(e));
    }
  }

  async function importFromGithub() {
    setJobResults(null);
    setJobError(null);
    setJobId(null);
    setSelectedV(null);
    setSourceView(null);
    setJobStatus("cloning…");

    try {
      const r = await importGithub(ghUrl.trim(), ghBranch.trim() || "main");
      setJobId(r.jobId);
      setJobStatus("pending");

      const poll = async () => {
        try {
          const d = await getJob(r.jobId);
          setJobStatus(d.status);
          if (d.status === "done" || d.status === "error") {
            const res = d.results ?? null;
            if (res && !res.projectId) res.projectId = r.projectId; // ensure viewer can fetch files
            setJobResults(res);
            setJobError(d.error ?? null);
            refreshDashboard();
          } else {
            setTimeout(poll, 1500);
          }
        } catch (e: any) {
          setJobStatus("poll error");
          setJobError(String(e));
        }
      };
      poll();
    } catch (e: any) {
      setJobStatus("git import error");
      setJobError(String(e));
    }
  }

  // --- Vpoints code viewer ---

  function CodeBlock({ content, hl }: { content: string; hl: { start: number; end: number } }) {
    const lines = content.split("\n");
    return (
      <pre className="text-xs bg-gray-50 rounded border overflow-auto max-h-[520px]">
        {lines.map((ln, i) => {
          const n = i + 1;
          const active = n >= hl.start && n <= hl.end;
          return (
            <div key={i} className={`grid grid-cols-[60px_1fr] px-2 ${active ? "bg-yellow-100" : ""}`}>
              <span className="text-gray-400 text-right pr-2 select-none">{n}</span>
              <code className="whitespace-pre-wrap break-words">{ln || " "}</code>
            </div>
          );
        })}
      </pre>
    );
  }

  async function openVPoint(v: any) {
    setSelectedV(v);
    setSourceView(null);
    try {
      const projId =
        v.projectId ||
        jobResults?.projectId ||
        jobs.find((j) => j.id === jobId)?.projectId;
      if (!projId) {
        setJobError("Missing projectId for file fetch");
        return;
      }
      const file = await getProjectFile(projId, v.path);
      setSourceView({ path: file.path, content: file.content });
    } catch (e: any) {
      setJobError(String(e));
    }
  }

  return (
    <div className="min-h-screen grid place-items-center bg-gray-50">
      <div className="p-6 rounded-2xl shadow bg-white space-y-4 w-[1100px]">
        <h1 className="text-2xl font-bold">AI-Enhanced Code Review</h1>

        <pre className="text-xs bg-gray-100 p-2 rounded">API: {JSON.stringify(api)}</pre>

        <div className="flex items-center justify-between">
          <div className="text-sm">
            {loading ? "Auth: loading..." : user ? `Auth: ${user.email}` : "Auth: signed out"}
          </div>
          <div className="space-x-2">
            {!user && (
              <>
                <button
                  className="px-3 py-1 rounded bg-black text-white"
                  onClick={() => signInWithPopup(auth, googleProvider)}
                >
                  Google
                </button>
                <button
                  className="px-3 py-1 rounded bg-slate-700 text-white"
                  onClick={() => signInWithPopup(auth, githubProvider)}
                >
                  GitHub
                </button>
              </>
            )}
            {user && (
              <button
                className="px-3 py-1 rounded bg-rose-600 text-white"
                onClick={() => signOut(auth)}
              >
                Sign out
              </button>
            )}
          </div>
        </div>

        <div className="space-x-2">
          <button className="px-3 py-1 rounded bg-indigo-600 text-white" onClick={loadMe}>
            Call /me (protected)
          </button>
        </div>

        <pre className="text-xs bg-gray-100 p-2 rounded">/me: {JSON.stringify(me)}</pre>

        <hr className="my-2" />

        {/* Run new analysis via ZIP */}
        <div className="space-y-3">
          <button className="px-4 py-2 rounded bg-teal-600 text-white" onClick={runAnalysis}>
            Upload .zip → Run Analysis
          </button>

          {/* Import from GitHub section */}
          <div className="border rounded p-3 space-y-2">
            <h2 className="font-semibold">Import from GitHub</h2>
            <div className="flex gap-2">
              <input
                value={ghUrl}
                onChange={(e) => setGhUrl(e.target.value)}
                placeholder="https://github.com/owner/repo or repo.git"
                className="flex-1 border rounded px-2 py-1 text-sm"
              />
              <input
                value={ghBranch}
                onChange={(e) => setGhBranch(e.target.value)}
                placeholder="main"
                className="w-40 border rounded px-2 py-1 text-sm"
              />
              <button
                className="px-3 py-1 rounded bg-emerald-600 text-white"
                onClick={importFromGithub}
                disabled={!ghUrl.trim()}
              >
                Import → Run
              </button>
            </div>
            <p className="text-xs text-gray-500">
              Public repos work out of the box. For private repos set <code>GITHUB_TOKEN</code> in the backend <code>.env</code>.
            </p>
          </div>

          <div className="text-sm">
            Job status: <span className="font-medium">{jobStatus}</span>
            {jobId ? <span className="ml-2 text-xs text-gray-500">({jobId})</span> : null}
          </div>

          {jobError && (
            <pre className="text-xs bg-rose-50 text-rose-700 p-2 rounded">
              {jobError}
            </pre>
          )}

          {/* AI Summary panel */}
          {jobResults?.ai && (
            <div className="border rounded p-3 space-y-2">
              <h2 className="font-semibold">AI Summary</h2>
              {jobResults.ai.error ? (
                <div className="text-sm text-rose-600">{jobResults.ai.error}</div>
              ) : (
                <>
                  <p className="text-sm">{jobResults.ai.summary}</p>

                  {!!(jobResults.ai.checklist?.length) && (
                    <>
                      <h3 className="font-semibold mt-2">Checklist</h3>
                      <ul className="list-disc pl-5 text-sm">
                        {jobResults.ai.checklist.map((c: any, i: number) => (
                          <li key={i} className="mb-1">
                            <span className="font-medium">{c.title}</span>
                            {c.severity && (
                              <span className="ml-2 text-xs text-gray-500">({c.severity})</span>
                            )}
                            {c.why && <div className="text-gray-700">Why: {c.why}</div>}
                            {c.how && <div className="text-gray-600">How: {c.how}</div>}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}

                  {!!(jobResults.ai.top_wins?.length) && (
                    <>
                      <h3 className="font-semibold mt-2">Top wins</h3>
                      <ul className="list-disc pl-5 text-sm">
                        {jobResults.ai.top_wins.map((t: string, i: number) => (
                          <li key={i}>{t}</li>
                        ))}
                      </ul>
                    </>
                  )}
                </>
              )}
            </div>
          )}

          {/* Findings/vpoints panel */}
          {Array.isArray(jobResults?.vpoints) && jobResults.vpoints.length > 0 && (
            <div className="border rounded p-3 space-y-2">
              <h2 className="font-semibold">Findings</h2>
              <ul className="divide-y">
                {jobResults.vpoints.map((v: any, idx: number) => (
                  <li key={idx} className="py-2 flex items-start justify-between gap-3">
                    <div className="text-sm">
                      <div className="flex gap-2 items-center flex-wrap">
                        <span className="rounded px-2 py-0.5 text-xs bg-gray-100">{v.tool}</span>
                        <span
                          className={`rounded px-2 py-0.5 text-xs ${
                            v.severity === "high"
                              ? "bg-rose-100 text-rose-700"
                              : v.severity === "medium"
                              ? "bg-yellow-100 text-yellow-700"
                              : "bg-green-100 text-green-700"
                          }`}
                        >
                          {v.severity}
                        </span>
                        {v.code && <span className="text-xs text-gray-500">{v.code}</span>}
                      </div>
                      <div className="font-medium">{v.message}</div>
                      <div className="text-xs text-gray-600">
                        {v.path}:{v.line}
                        {v.endLine && v.endLine !== v.line ? `-${v.endLine}` : ""}
                      </div>
                    </div>
                    <button
                      className="text-indigo-600 underline text-sm shrink-0"
                      onClick={() => openVPoint({ ...v, projectId: jobResults?.projectId })}
                      title="Open in viewer"
                    >
                      View code
                    </button>
                  </li>
                ))}
              </ul>

              {/* Inline source viewer */}
              {selectedV && sourceView && (
                <div className="mt-3">
                  <div className="mb-1 text-sm text-gray-600 font-mono">{sourceView.path}</div>
                  <CodeBlock
                    content={sourceView.content}
                    hl={{
                      start: selectedV.line || 1,
                      end: selectedV.endLine || selectedV.line || 1,
                    }}
                  />
                </div>
              )}
            </div>
          )}

          {/* Raw results for debugging */}
          <details className="text-xs">
            <summary className="cursor-pointer select-none">Raw results (debug)</summary>
            <pre className="bg-gray-100 p-2 rounded max-h-96 overflow-auto">
              {jobResults ? JSON.stringify(jobResults, null, 2) : ""}
            </pre>
          </details>
        </div>

        {/* Jobs Dashboard */}
        <hr className="my-4" />
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-lg">Jobs Dashboard</h2>
            <button className="px-3 py-1 rounded bg-gray-800 text-white" onClick={refreshDashboard}>
              Refresh
            </button>
          </div>

          {/* Project filter */}
          <div className="flex items-center gap-2">
            <label className="text-sm">Project:</label>
            <select
              className="border rounded px-2 py-1 text-sm"
              value={selectedProject}
              onChange={async (e) => {
                const pid = e.target.value as string | "all";
                setSelectedProject(pid);
                const j = await listJobs({
                  projectId: pid === "all" ? undefined : pid,
                  limit: 50,
                });
                setJobs(j.items || []);
              }}
            >
              <option value="all">All</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name || p.id}
                </option>
              ))}
            </select>
          </div>

          {/* Jobs table */}
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500">
                  <th className="py-2 pr-4">Job</th>
                  <th className="py-2 pr-4">Project</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">AI</th>
                  <th className="py-2 pr-4">Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id} className="border-t">
                    <td className="py-2 pr-4 font-mono text-xs">{j.id.slice(0, 8)}…</td>
                    <td className="py-2 pr-4">{j.projectId}</td>
                    <td className="py-2 pr-4">
                      <span
                        className={`px-2 py-0.5 rounded text-xs ${
                          j.status === "done"
                            ? "bg-green-100 text-green-700"
                            : j.status === "running"
                            ? "bg-yellow-100 text-yellow-700"
                            : j.status === "error"
                            ? "bg-rose-100 text-rose-700"
                            : "bg-gray-100 text-gray-700"
                        }`}
                      >
                        {j.status}
                      </span>
                    </td>
                    <td className="py-2 pr-4">
                      {j.results?.ai?.summary ? "✓" : j.status === "done" ? "—" : ""}
                    </td>
                    <td className="py-2 pr-4 space-x-2">
                      <button
                        className="text-indigo-600 underline"
                        onClick={() => {
                          setJobId(j.id);
                          const jr = j.results || null;
                          if (jr && !jr.projectId) jr.projectId = j.projectId; // ensure viewer can fetch files
                          setJobResults(jr);
                          setJobError(j.error || null);
                          setJobStatus(j.status);
                          setSelectedV(null);
                          setSourceView(null);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      >
                        View
                      </button>
                      <button
                        className="text-gray-700 underline"
                        onClick={async () => {
                          const r = await createJob(j.projectId);
                          setJobId(r.id);
                          setJobResults(null);
                          setJobError(null);
                          setSelectedV(null);
                          setSourceView(null);
                          setJobStatus("pending");
                          const tick = async () => {
                            const d = await getJob(r.id);
                            setJobStatus(d.status);
                            if (d.status === "done" || d.status === "error") {
                              const out = d.results ?? null;
                              if (out && !out.projectId) out.projectId = j.projectId;
                              setJobResults(out);
                              setJobError(d.error ?? null);
                              refreshDashboard();
                            } else {
                              setTimeout(tick, 1500);
                            }
                          };
                          tick();
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      >
                        Re-run
                      </button>
                    </td>
                  </tr>
                ))}
                {!jobs.length && (
                  <tr>
                    <td className="py-6 text-gray-500" colSpan={5}>
                      No jobs yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
