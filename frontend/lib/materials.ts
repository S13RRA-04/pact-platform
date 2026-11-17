import { api } from "./api";

export type Material = {
  id: number; document_code: string; title: string; media_type: string; byte_size: number; audience: string | null;
  approval_status: string; release_day: string | null; release_block: string | null; released_at: string | null;
  cohort_code: string | null;
};

/** Ask the server for a short-lived, user-bound link (access is re-checked when it is used), then follow it. */
export async function downloadMaterial(id: number): Promise<void> {
  const { url } = await api<{ url: string; expires_in: number }>(`/api/materials/${id}/download-link`, { method: "POST" });
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export function fileKind(mediaType: string): string {
  if (mediaType.includes("wordprocessingml")) return "Word";
  if (mediaType.includes("presentationml")) return "Slides";
  if (mediaType.includes("spreadsheetml")) return "Excel";
  if (mediaType === "text/csv") return "CSV";
  if (mediaType === "text/markdown") return "Markdown";
  if (mediaType === "application/json") return "JSON";
  return "Text";
}

export const kb = (bytes: number) => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);
