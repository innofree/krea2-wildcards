export const meta = {
  name: 'review-axis-sheets',
  description: 'Review one Phase 7 axis run\'s contact sheets in parallel, one agent per sheet, then verify held cases at full resolution',
  whenToUse:
    'After `make phase7-axis-sheets` has built the sheets and crib for an axis. Replaces paging 30 sheets serially: each sheet is an independent verdict, so they fan out, and the images never enter the orchestrator\'s context.',
  phases: [
    { title: 'Review', detail: 'one agent per contact sheet, verdict + reasoning per case' },
    { title: 'Verify', detail: 'reopen every held case at full resolution before it sticks' },
  ],
}

// args can arrive as an object or as a JSON string depending on how the caller
// passes it, and a bare axis name is convenient enough to accept too.
function readArgs(raw) {
  if (!raw) return {}
  if (typeof raw !== 'string') return raw
  const text = raw.trim()
  if (!text.startsWith('{')) return { axis: text }
  try {
    return JSON.parse(text)
  } catch {
    return { axis: text }
  }
}

const input = readArgs(args)
const axis = input.axis
const rev = input.rev ?? 'v2'
if (!axis) {
  throw new Error(
    `args.axis is required, e.g. {"axis":"linework_coloring","rev":"v2"} -- received ${JSON.stringify(args)}`,
  )
}

const reportDir = `tests/reports/phase7_${axis}_${rev}`
const reviewDir = `${reportDir}/review`

const VERDICTS = {
  type: 'object',
  additionalProperties: false,
  required: ['sheet_index', 'cases'],
  properties: {
    sheet_index: { type: 'integer' },
    cases: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['alias', 'verdict', 'reasoning'],
        properties: {
          alias: { type: 'string', description: 'e.g. case_001' },
          verdict: { enum: ['pass', 'hold'] },
          reasoning: {
            type: 'string',
            description:
              'Name the crib attributes and what was actually visible. One line.',
          },
          needs_full_resolution: {
            type: 'boolean',
            description:
              'true when the sheet thumbnail cannot settle this case on its own',
          },
        },
      },
    },
  },
}

const CONFIRM = {
  type: 'object',
  additionalProperties: false,
  required: ['alias', 'holds', 'reasoning'],
  properties: {
    alias: { type: 'string' },
    holds: {
      type: 'boolean',
      description: 'true if the defect is still there at full resolution',
    },
    reasoning: { type: 'string' },
  },
}

// The manifest is the only source of truth for which cases are on which sheet.
// Reading it here rather than letting each agent parse it keeps the agents from
// disagreeing about the mapping.
const manifest = await agent(
  `Read ${reviewDir}/manifest.json and return every sheet with its image path and the aliases on it. Do not open any image.`,
  {
    label: 'read:manifest',
    phase: 'Review',
    effort: 'low',
    schema: {
      type: 'object',
      additionalProperties: false,
      required: ['sheets'],
      properties: {
        sheets: {
          type: 'array',
          items: {
            type: 'object',
            additionalProperties: false,
            required: ['sheet_index', 'path', 'aliases'],
            properties: {
              sheet_index: { type: 'integer' },
              path: { type: 'string' },
              aliases: { type: 'array', items: { type: 'string' } },
            },
          },
        },
      },
    },
  },
)

// input.sheets restricts this run to a batch, e.g. {"sheets":[1,20]} for sheets
// 1-20 inclusive, or {"sheets":[21,40]} for the rest. Large axes (400+ cases,
// 40 sheets) hit the org's spend limit hard enough mid-run to fail sheets that
// never even got reviewed once, not just the verification pass -- splitting the
// review into batches keeps one failure from taking out the whole axis.
const [batchStart, batchEnd] = Array.isArray(input.sheets) ? input.sheets : [null, null]
const sheets = (manifest?.sheets ?? [])
  .filter(Boolean)
  .filter((s) => batchStart == null || (s.sheet_index >= batchStart && s.sheet_index <= batchEnd))
if (!sheets.length) throw new Error(`no sheets found in ${reviewDir}/manifest.json`)
log(`${sheets.length} sheet(s) to review for ${axis} ${rev}`)

const reviewBrief = (sheet) => `Review contact sheet ${sheet.sheet_index} of the Phase 7 \`${axis}\` axis run.

Sheet image: ${sheet.path}
Crib:        ${reviewDir}/crib.txt
Catalog:     read the item's feature_axes if the crib is ambiguous.

Aliases on this sheet: ${sheet.aliases.join(', ')}

Read the crib section for "sheet ${String(sheet.sheet_index).padStart(3, '0')}" FIRST. It pairs each
alias with the catalog attributes that case is supposed to express. Judge against
those attributes, never against what you'd infer from a case's position on the
sheet — a rule was once recorded into plan.md because a reviewer inferred an
attribute from position and was wrong.

Then open the sheet image and give every alias a verdict.

- \`pass\`  — the named attributes are visibly expressed on the figure.
- \`hold\`  — not approvable on this evidence. That covers BOTH a real defect AND an
             attribute you simply cannot read at this density. Say which one it is
             in the reasoning; they are treated differently downstream.

If an attribute the crib marks [EXCLUDED] is unreadable, that is expected and must
not produce a hold on its own.

Set \`needs_full_resolution: true\` on any case where the thumbnail is genuinely too
small to decide — especially colour saturation and fine linework. Do not guess. A
later phase reopens those at 1024x1024.

Reasoning must name the crib attributes and what you actually saw, one line, e.g.
"angular_precise + deep_jewel + broad_blended_plane: angular colour-block facets in
true jewel saturation (green/maroon/navy)". Do not write "looks correct".`

const reviewed = await parallel(
  sheets.map((sheet) => () =>
    agent(reviewBrief(sheet), {
      label: `sheet:${String(sheet.sheet_index).padStart(3, '0')}`,
      phase: 'Review',
      schema: VERDICTS,
    }),
  ),
)

const results = reviewed.filter(Boolean)
const dropped = sheets.length - results.length
if (dropped) log(`WARNING: ${dropped} sheet(s) returned nothing and are not in the output`)

// Every hold, and every case the reviewer flagged as undecidable, gets reopened at
// full resolution. This is the step plan.md 7.18 skipped: its holds came from
// thumbnails, and the finding did not survive a full-resolution look.
const toVerify = results.flatMap((sheet) =>
  sheet.cases
    .filter((c) => c.verdict === 'hold' || c.needs_full_resolution)
    .map((c) => ({ ...c, sheet_index: sheet.sheet_index })),
)
log(`${toVerify.length} case(s) to reopen at full resolution`)

phase('Verify')
const confirmations = await parallel(
  toVerify.map((c) => () =>
    agent(
      `Case \`${c.alias}\` of the Phase 7 \`${axis}\` axis was marked "${c.verdict}" from a contact sheet thumbnail with this reasoning:

  ${c.reasoning}

Resolve its full-resolution render and decide whether that still holds.

1. Find the case's test_id: it is the row in ${reportDir}/scorecard.csv whose
   style_id matches \`${c.alias}\` in ${reviewDir}/manifest.json.
2. Open ${reportDir}/runs/<test_id>/image_01.png at full size — all seeds if they
   disagree.
3. If the concern was colour saturation, also read
   ${reportDir}/saturation_screen.json if it exists. It reports this item's mean
   saturation against the median of its OWN palette group. A low absolute number
   is not a defect: airy_pastel renders near 0.10 by design. Only a value well
   below its own group's median is evidence.

Return holds=true only if the defect is genuinely visible at full resolution.
Return holds=false if it was a thumbnail artifact — that is a real and expected
outcome, not a failure to find something.`,
      {
        label: `verify:${c.alias}`,
        phase: 'Verify',
        schema: CONFIRM,
      },
    ),
  ),
)

const overturned = new Map(
  confirmations.filter(Boolean).filter((c) => c.holds === false).map((c) => [c.alias, c]),
)

// Emit the format build_phase7_review_yaml.py already consumes:
// review_parts/sNNN.json = { case_NNN: [verdict, reasoning] }
// Only a hold can be overturned. A pass routed to verification for
// needs_full_resolution comes back holds=false too, and treating that as an
// overturn writes "overturned at full resolution" onto a case where nothing was
// ever in question -- it reads as though a defect had been found and dismissed.
const parts = results.map((sheet) => {
  const body = {}
  for (const c of sheet.cases) {
    const flip = c.verdict === 'hold' ? overturned.get(c.alias) : undefined
    body[c.alias] = flip
      ? ['pass', `${c.reasoning} -- overturned at full resolution: ${flip.reasoning}`]
      : [c.verdict, c.reasoning]
  }
  return { sheet_index: sheet.sheet_index, body }
})

return {
  axis,
  rev,
  review_parts_dir: `${reportDir}/review_parts`,
  sheets_reviewed: results.length,
  sheets_dropped: dropped,
  cases: parts.reduce((n, p) => n + Object.keys(p.body).length, 0),
  holds_after_verification: parts.reduce(
    (n, p) => n + Object.values(p.body).filter(([v]) => v === 'hold').length,
    0,
  ),
  overturned_by_full_resolution: [...overturned.keys()].sort(),
  parts,
  next: [
    `Write each parts[].body to ${reportDir}/review_parts/s<NNN>.json (3-digit, zero padded).`,
    `python3 scripts/build_phase7_review_yaml.py ${reviewDir}/manifest.json ${reportDir}/review_parts --output ${reportDir}/review.yaml`,
    `make phase7-axis-apply AXIS=${axis} REV=${rev} CATALOG=catalog/<plural>.yaml`,
  ],
}
