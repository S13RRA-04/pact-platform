export const TYPE_LABEL: Record<string, string> = {
  evidence_inject: "Evidence",
  document: "Document",
  document_block: "Documents",
  challenge: "Challenge",
  debrief: "Debrief",
  answer_key: "Answer key",
};

export const AUDIENCE_LABEL: Record<string, string> = {
  all_students: "All students",
  investigator: "Investigators",
  analyst: "Analysts",
  staff: "Staff only",
};

/** Squad release track: "case:A" → only squads assigned case A; "site:418" → only that search-site team. */
export function trackLabel(track: string | null | undefined): string | null {
  if (!track) return null;
  const [kind, label] = track.split(":");
  return kind === "case" ? `Case ${label} squads only` : kind === "site" ? `Site team ${label} only` : track;
}

/** "All students" + "case:A" reads as "Case A squads only"; a pathway-limited item keeps both parts. */
export function audienceText(audience: string, track: string | null | undefined): string {
  const t = trackLabel(track);
  if (!t) return AUDIENCE_LABEL[audience] ?? audience;
  return audience === "all_students" ? t : `${AUDIENCE_LABEL[audience]} · ${t}`;
}

export const TRACK_OPTIONS: [string, string][] = [
  ["", "Every squad"],
  ["case:A", "Case A squads"], ["case:B", "Case B squads"], ["case:C", "Case C squads"], ["case:D", "Case D squads"],
  ["site:418", "Site team 418"], ["site:R12", "Site team R12"], ["site:C14", "Site team C14"],
];

export const STATE_TONE: Record<string, string> = {
  released: "success",
  pending: "neutral",
  held: "warning",
  withdrawn: "danger",
};

type Trigger = {
  trigger_type: string;
  trigger_day: string | null;
  trigger_time: string | null;
  trigger_module_code: string | null;
  trigger_lesson_state: string | null;
  trigger_after_code: string | null;
};

export function triggerText(i: Trigger): string {
  switch (i.trigger_type) {
    case "scheduled":
      return `${i.trigger_day} ${i.trigger_time}`;
    case "lesson_gate":
      return `When ${i.trigger_module_code} is ${i.trigger_lesson_state}`;
    case "after_item":
      return `After ${i.trigger_after_code}`;
    default:
      return "Instructor releases";
  }
}
