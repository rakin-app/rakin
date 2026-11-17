import { queryOptions } from "@tanstack/react-query";
import { apiFetch, ApiError } from "./client";

/** What a sheet column can be, in the order the mapping offers them. */
export const IMPORT_FIELDS = [
  "name",
  "last_name",
  "phone",
  "email",
  "rut",
  "dob",
  "plan",
  "due_on",
  "started_on",
  "guardian_name",
  "guardian_rut",
  "guardian_email",
  "guardian_phone",
  // History from before Rakin (#297): only where the gym has none yet.
  "member_since",
  "left_on",
  "left_reason",
  "prior_classes",
] as const;
export type ImportField = (typeof IMPORT_FIELDS)[number];

export type Mapping = Partial<Record<ImportField, number>>;

export type SheetRow = { number: number; cells: string[] };

// The file the sheet was read from, sent back so the import's record names it.
export type SheetFile = { name: string | null; sha256: string };

/** A Pagos tab's column (#298): one row per payment received before Rakin. */
export const PAYMENT_FIELDS = [
  "rut",
  "email",
  "name",
  "paid_on",
  "amount_clp",
  "covers_month",
  "method",
  "plan_name",
  "note",
] as const;
export type PaymentField = (typeof PAYMENT_FIELDS)[number];
export type PaymentMapping = Partial<Record<PaymentField, number>>;

export type PaymentSheet = {
  headers: string[];
  rows: SheetRow[];
  mapping: PaymentMapping;
};

/** A Grados tab's column (#299): one row per belt or stripe earned. */
export const GRADE_FIELDS = [
  "rut",
  "email",
  "name",
  "rank",
  "sub_rank",
  "awarded_on",
  "note",
] as const;
export type GradeField = (typeof GRADE_FIELDS)[number];
export type GradeMapping = Partial<Record<GradeField, number>>;

export type GradeSheet = {
  headers: string[];
  rows: SheetRow[];
  mapping: GradeMapping;
};

/** The tabs a workbook is read by; a CSV is one of them, chosen on upload. */
export const SHEET_TABS = ["alumnos", "pagos", "grados"] as const;
export type SheetTab = (typeof SHEET_TABS)[number];

/** The Alumnos tab at the top level (no headers and no rows in a workbook without one), the others beside it. */
export type Sheet = {
  headers: string[];
  rows: SheetRow[];
  mapping: Mapping;
  file: SheetFile;
  pagos: PaymentSheet | null;
  grados: GradeSheet | null;
};

export type RowErrorCode =
  | "required"
  | "repeated"
  | "invalid_phone"
  | "invalid_email"
  | "invalid_rut"
  | "invalid_date"
  | "own_guardian"
  | "unknown_plan"
  | "inactive_plan"
  | "dropin_plan"
  // A fixed-period plan whose period ended before the due date (#351).
  | "ended_plan"
  | "due_before_start"
  | "has_guardian"
  | "one_level"
  // Dado de baja: reactivated from their ficha, never by a sheet (#157).
  | "has_left"
  // Two of the name in the gym, and nothing else tells them apart (#165).
  | "ambiguous_name"
  // The RUT or email the row would give someone is another person's in this gym.
  | "rut_in_gym"
  | "email_in_gym"
  // "Fecha de baja" before "Alumno desde".
  | "left_before_start"
  // "Clases antes de Rakin" is not a whole number.
  | "invalid_number"
  // "Motivo de baja" over 200 characters.
  | "too_long"
  // Under 18 by the birth date, and the row names no guardian (#368).
  | "minor";

export type Outcome = "created" | "existing";

export type RowResult = {
  row: number;
  name: string;
  errors: { field: ImportField; code: RowErrorCode }[];
  person: Outcome | null;
  guardian: Outcome | null;
  link: Outcome | null;
  membership: Outcome | null;
  // Fields the import leaves unapplied: whoever it found keeps this gym's record.
  ignored: ImportField[];
  // Whom the gym messages about them (their guardian, for a kid) has no phone:
  // imported, and flagged "Falta teléfono" until one is filled in.
  missing_phone: boolean;
  // Neither a RUT nor an email: imported, and found again by their name in this gym.
  missing_identity: boolean;
  // It wrote some of their history from before Rakin, where the gym had none.
  history: boolean;
  // A former student's row: one with a "Fecha de baja", imported with no plan.
  former: boolean;
};

export type PaymentRowErrorCode =
  | "required"
  | "invalid_rut"
  | "invalid_email"
  | "invalid_date"
  // Not whole pesos above zero.
  | "invalid_amount"
  // None of Efectivo, Transferencia, Otro.
  | "invalid_method"
  // Nobody in the gym or on the Alumnos tab is the row: a payment creates no one.
  | "unknown_person"
  | "ambiguous_name"
  // On or after their first plan here: that month is paid with "Pagado hasta".
  | "covers_plan"
  // An earlier row gives them the same day, amount and month.
  | "repeated"
  | "too_long";

export type PaymentRowResult = {
  row: number;
  name: string;
  errors: { field: PaymentField; code: PaymentRowErrorCode }[];
  // `existing`: they already had a payment of that day, amount and month.
  payment: Outcome | null;
};

export type PaymentReport = {
  summary: {
    rows: number;
    imported: number;
    refused: number;
    payments_created: number;
    amount_clp: number;
  };
  rows: PaymentRowResult[];
};

export type GradeRowErrorCode =
  | "required"
  | "invalid_rut"
  | "invalid_email"
  | "invalid_date"
  // No rank (or sub-rank) of the scheme by that label, and none chosen.
  | "unknown_rank"
  // Nobody in the gym or on the Alumnos tab is the row: a grade creates no one.
  | "unknown_person"
  | "ambiguous_name"
  // An earlier row gives them the same grade on the same day.
  | "repeated"
  | "too_long";

export type GradeRowResult = {
  row: number;
  name: string;
  errors: { field: GradeField; code: GradeRowErrorCode }[];
  // `existing`: they already had that grade on that day.
  grade: Outcome | null;
};

export type GradeReport = {
  summary: {
    rows: number;
    imported: number;
    refused: number;
    grades_created: number;
  };
  rows: GradeRowResult[];
};

export type ImportReport = {
  dry_run: boolean;
  // The import's record in the gym's log; never on a dry run, nor when nothing was written.
  import_id: string | null;
  summary: {
    rows: number;
    imported: number;
    refused: number;
    people_created: number;
    links_created: number;
    memberships_created: number;
    // Rows imported with "Falta teléfono".
    missing_phone: number;
    missing_identity: number;
    // People whose history it wrote, and the former students it created.
    history_set: number;
    former_created: number;
  };
  rows: RowResult[];
  pagos: PaymentReport | null;
  grados: GradeReport | null;
};

const SHEET_REFUSALS = [
  "unreadable",
  "empty",
  "too_many_rows",
  "too_many_empty_rows",
  "too_large",
] as const;
export type SheetRefusal = (typeof SHEET_REFUSALS)[number];

// The API's own limit is 5 MB; refusing here spares the upload.
export const MAX_SHEET_BYTES = 5 * 1024 * 1024;
export const SHEET_TYPES = [
  ".csv",
  ".xlsx",
  "text/csv",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
];

/** Read the file into rows; nothing is stored. A CSV is `tab`; a workbook says by its tabs' names. */
export function uploadSheet(
  file: File,
  tab: SheetTab = "alumnos",
): Promise<Sheet> {
  return apiFetch<Sheet>(
    `/api/import/sheet?${new URLSearchParams({ name: file.name, tab })}`,
    {
      method: "POST",
      body: file,
      headers: { "Content-Type": file.type || "application/octet-stream" },
    },
  );
}

export type ImportRequest = {
  rows: SheetRow[];
  mapping: Mapping;
  // A plan cell's value to the plan it means; `null` for no plan, the person alone.
  plans: Record<string, string | null>;
  dry_run: boolean;
  file?: SheetFile;
  pagos?: { rows: SheetRow[]; mapping: PaymentMapping };
  grados?: {
    rows: SheetRow[];
    mapping: GradeMapping;
    // A Grado cell's value to the rank key it means, for values that are not a rank's label.
    ranks: Record<string, string>;
  };
};

/** Rakin's sheet to fill in (#297): a file the browser downloads, not JSON. */
export const TEMPLATE_PATH = "/api/import/template.xlsx";

export function runImport(body: ImportRequest): Promise<ImportReport> {
  return apiFetch<ImportReport>("/api/import/members", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Why the API refused a file, when it said. */
export function sheetRefusal(error: unknown): SheetRefusal | null {
  if (!(error instanceof ApiError)) return null;
  const detail = (error.body as { detail?: { code?: unknown } } | undefined)
    ?.detail;
  const code =
    typeof detail === "object" && detail !== null ? detail.code : undefined;
  return SHEET_REFUSALS.find((refusal) => refusal === code) ?? null;
}

/** For matching a plan cell to a plan's name, as the API does: accents, case and spacing ignored. */
export function fold(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

/** An import's undo (#300): when, by whom, why, and what it removed. */
export type ImportUndone = {
  at: string;
  by: string | null;
  reason: string;
  payments: number;
  grades: number;
  people: number;
  kept: number;
};

/** A line of Importar's recent imports. `counts` is per tab, as each tab's summary has it. */
export type RecentImport = {
  id: string;
  at: string;
  // The name the gym has for whoever imported; null once they are deleted.
  by: string | null;
  file_name: string | null;
  tabs: SheetTab[];
  counts: Partial<Record<SheetTab, Record<string, number>>>;
  undone: ImportUndone | null;
};

/** The gym's latest imports, newest first. Owner and admin. */
export function recentImportsQuery() {
  return queryOptions({
    queryKey: ["import", "recent"],
    queryFn: () => apiFetch<RecentImport[]>("/api/import/recent"),
  });
}

/** What "Deshacer importación" would remove, and the fields changed since, which stay. */
export type UndoCounts = {
  payments: number;
  grades: number;
  people: number;
  kept: number;
};

const undoPath = (id: string) => `/api/import/${encodeURIComponent(id)}/undo`;

/** Owner only. */
export function undoCountsQuery(id: string) {
  return queryOptions({
    queryKey: ["import", "undo", id],
    queryFn: () => apiFetch<UndoCounts>(undoPath(id)),
  });
}

/** The history the import wrote, gone: its payments and grades, and the fields it set put back. */
export function undoImport(id: string, reason: string): Promise<void> {
  return apiFetch<void>(undoPath(id), {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

/** Whether the API refused because the import was already undone. */
export function alreadyUndone(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 409) return false;
  return (
    (error.body as { detail?: { code?: unknown } } | undefined)?.detail
      ?.code === "undone"
  );
}
