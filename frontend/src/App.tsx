import { useEffect, useState } from "react";
import { ping, whoAmI, createProject, createJob, uploadZip, getJob } from "./lib/api";
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

  useEffect(() => {
    ping().then(setApi).catch((e) => setApi({ error: true, msg: String(e) }));
  }, []);

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
                setJobResults(data.results ?? null);
                if (data.status === "error") setJobError(data.error ?? "Job failed");
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

  return (
    <div className="min-h-screen grid place-items-center bg-gray-50">
      <div className="p-6 rounded-2xl shadow bg-white space-y-4 w-[720px]">
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

        <div className="space-y-2">
          <button className="px-4 py-2 rounded bg-teal-600 text-white" onClick={runAnalysis}>
            Upload .zip → Run Analysis
          </button>

          <div className="text-sm">
            Job status: <span className="font-medium">{jobStatus}</span>
            {jobId ? <span className="ml-2 text-xs text-gray-500">({jobId})</span> : null}
          </div>

          {jobError && (
            <pre className="text-xs bg-rose-50 text-rose-700 p-2 rounded">
              {jobError}
            </pre>
          )}

          <pre className="text-xs bg-gray-100 p-2 rounded max-h-96 overflow-auto">
            {jobResults ? JSON.stringify(jobResults, null, 2) : ""}
          </pre>
        </div>
      </div>
    </div>
  );
}
