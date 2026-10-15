import { z } from "zod";
const short = z.string().trim().min(2).max(160);
const url = z.union([
  z.literal(""),
  z
    .string()
    .trim()
    .url()
    .max(1000)
    .refine((s) => /^https?:\/\//.test(s), "Use an HTTP or HTTPS URL"),
]);
export const briefSchema = z
  .object({
    businessName: short,
    industry: short,
    description: z.string().trim().min(20).max(4000),
    audience: z.string().trim().min(3).max(300),
    pages: z
      .array(z.enum(["Home", "About", "Services", "Contact", "Gallery", "FAQ"]))
      .min(1)
      .max(6),
    style: z.enum(["Warm & natural", "Clean & modern", "Bold & expressive"]),
    website: url.default(""),
  })
  .strict();
const text = z.string().trim().min(3).max(3000);
const requestId = z.string().uuid();
const serviceCategory = z.enum([
  "small_edit",
  "extra_page",
  "redesign",
  "advanced",
]);
export const actionSchema = z.discriminatedUnion("type", [
  z
    .object({
      type: z.literal("message"),
      text,
      serviceCategory: serviceCategory.optional(),
    })
    .strict(),
  z.object({ type: z.literal("accept_initial_quote") }).strict(),
  z
    .object({
      type: z.literal("request"),
      category: serviceCategory,
      description: text,
      assetUrl: url.default(""),
    })
    .strict(),
  z.object({ type: z.literal("accept_request"), requestId }).strict(),
  z.object({ type: z.literal("cancel_request"), requestId }).strict(),
  z.object({ type: z.literal("generate_preview") }).strict(),
  z.object({ type: z.literal("set_sources"), folderUrl: z.string().max(600), consent: z.literal(true) }).strict(),
  z.object({ type: z.literal("stop_pipeline") }).strict(),
  z.object({ type: z.literal("resume_pipeline") }).strict(),
  z
    .object({
      type: z.literal("approve_preview"),
      previewVersion: z.number().int().positive(),
    })
    .strict(),
  z
    .object({
      type: z.literal("preview_feedback"),
      previewVersion: z.number().int().positive(),
      text,
    })
    .strict(),
]);
export const createSchema = z.object({ brief: briefSchema }).strict();
export const updateSchema = z
  .object({ revision: z.number().int().positive(), action: actionSchema })
  .strict();
export type Brief = z.infer<typeof briefSchema>;
export type ServiceCategory = z.infer<typeof serviceCategory>;
export type Message = {
  id: string;
  role: string;
  text: string;
  at: string;
  // Older stored messages may lack metadata; all new messages use the server's project ID.
  projectId?: string;
  kind?: "initial_quote" | "request" | "status";
  requestId?: string;
};
export type Project = {
  id: string;
  name: string;
  revision: number;
  createdAt: string;
  updatedAt: string;
  sample: boolean;
  brief: Brief;
  status: string;
  subscription: string;
  initialQuote: {
    status: string;
    cents: number;
    monthlyCents: number;
    version: number;
  };
  preview: null | {
    generated?: boolean;
    sha256?: string;
    externalUrl?: string;
    jobId?: string;
    buildRevision?: string;
    version: number;
    status: string;
    at: string;
    approvalAt: string | null;
    feedback: string;
  };
  integration?: { requestId: string; status: string; kind: string; messageId: string };
  pipeline?: {
    state: string; questions: string[]; missingFields: string[]; reasonCodes?: string[]; resumes?: number;
    facts?: { field: string; value: string; quote: string; source: string }[];
    sources?: { folderUrl?: string; status: string; files: { name: string; mimeType: string; version: string }[]; pages?: number; characters?: number };
    build?: { jobId: string; status: string };
  };
  requests: {
    id: string;
    category: string;
    title: string;
    description: string;
    assetUrl: string;
    status: string;
    cents: number | null;
    at: string;
    quoteVersion: number;
  }[];
  messages: Message[];
  activity: { id: string; text: string; at: string }[];
};
