export const TYPE_LABEL: Record<string, string> = {
  evidence_inject: "Evidence",
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
