import { auth } from "./firebase";

export async function ping() {
  const res = await fetch(`/api/health`, await withAuth({ method: "GET" }));
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function whoAmI() {
  const res = await fetch(`/api/me`, await withAuth({ method: "GET" }));
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}
export async function createProject(name: string, source: string) {
  const res = await fetch(`/api/projects`, await withAuth({
    method: "POST",
    body: JSON.stringify({ name, source }),
  }));
  const text = await res.text();
  if (!res.ok) throw new Error(text);
  return JSON.parse(text);
}

export async function createJob(projectId: string) {
  const res = await fetch(`/api/jobs`, await withAuth({
    method: "POST",
    body: JSON.stringify({ projectId }),
  }));
  const text = await res.text();
  if (!res.ok) throw new Error(text);
  return JSON.parse(text);
}

async function withAuth(init?: RequestInit): Promise<RequestInit> {
  const user = auth.currentUser;
  const token = user ? await user.getIdToken() : null;

  const headers = new Headers(init?.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);

  // Only set JSON content-type when body is NOT FormData
  const isFormData = init?.body instanceof FormData;
  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return { ...(init || {}), headers };
}

export async function uploadZip(projectId: string, file: File) {
  const form = new FormData();
  form.append("file", file);            // field name MUST be "file" to match FastAPI
  const res = await fetch(`/api/projects/${projectId}/upload`,
    await withAuth({ method: "POST", body: form })
  );
  const text = await res.text();
  if (!res.ok) throw new Error(text);
  return JSON.parse(text);
}


export async function getJob(jobId: string) {
  const res = await fetch(`/api/jobs/${jobId}`, await withAuth({ method: "GET" }));
  if (!res.ok) {
    // bubble up FastAPI's error message (e.g., {"detail":"job not found"})
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function listProjects(limit = 20) {
  const res = await fetch(`/api/projects?limit=${limit}`, await withAuth({ method: "GET" }));
  if (!res.ok) throw new Error(await res.text());
  return res.json(); // { items: [...] }
}

export async function listJobs(opts?: { projectId?: string; limit?: number }) {
  const q = new URLSearchParams();
  if (opts?.projectId) q.set("projectId", opts.projectId);
  if (opts?.limit) q.set("limit", String(opts.limit));
  const res = await fetch(`/api/jobs?${q.toString()}`, await withAuth({ method: "GET" }));
  if (!res.ok) throw new Error(await res.text());
  return res.json(); // { items: [...] }
}

export async function importGithub(repoUrl: string, branch: string = "main", name?: string) {
  const body: any = { repoUrl, branch };
  if (name) body.name = name;
  const res = await fetch(`/api/projects/github`, await withAuth({
    method: "POST",
    body: JSON.stringify(body),
  }));
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ projectId: string; jobId: string; status: string }>;
}