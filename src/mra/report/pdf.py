"""Report model -> PDF, inside a hard 14-page budget.

White page, black text, one grey for rules. Colour appears only where it
means something: the status (green / amber / red) and diff +/- markers, and
status always carries its word and symbol too, so it survives a black-and-white
printer. Amber is only ever a light fill behind dark text. Helvetica for text,
Courier for diffs (all three built into every PDF reader), and the three glyphs
Helvetica lacks (check, cross, arrow) from a 2 KB DejaVu Sans subset that is
embedded, so they print on any reader. One type scale; spacing on a 4 pt grid.

Every page but the first carries a header (repo, contract, status pill,
version); every page a footer (run id, the run's *recorded* completion time,
"Page X of Y" from a two-pass canvas). Nothing in either depends on when the
PDF is rendered, so ``mra report <run_id>`` reproduces it text-for-text; the
render time appears once, on page 1.

The budget is enforced by building, counting pages, and rebuilding with the
next truncation level until the document fits: diff excerpts go first, then
timeline detail, then file-table rows (then plan rows, as a last resort).
Every cut says "+N more — see report.json"; report.json is never cut.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import networkx as nx
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Circle, Drawing, Line, String
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import registerFont, stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

MAX_PAGES = 14
GRAPH_NODE_CAP = 30

FONT, BOLD, MONO, GLYPHS = "Helvetica", "Helvetica-Bold", "Courier", "MRAGlyphs"
#: U+2713, U+2715, U+2192 only (fonts/DejaVu-LICENSE.txt). Embedded, never referenced.
registerFont(TTFont(GLYPHS, Path(__file__).with_name("fonts") / "DejaVuSans-symbols.ttf"))
INK = colors.black
#: Strong colour (rules, banner edge, diff +/-), dark text, and light fill per status.
STATUS_HEX = {"GREEN": "#1E7B34", "YELLOW": "#B7791F", "RED": "#B42318"}
STATUS_INK = {"GREEN": "#14532D", "YELLOW": "#5C3D00", "RED": "#7F1D1D"}
STATUS_FILL = {"GREEN": "#E3F2E6", "YELLOW": "#FDF0CC", "RED": "#FBE3E1"}
#: (font, glyph) — Helvetica has no check or cross, so they come from GLYPHS.
SYMBOL = {"GREEN": (GLYPHS, "\u2713"), "YELLOW": (BOLD, "!"), "RED": (GLYPHS, "\u2715")}
STATUS = {name: colors.HexColor(value) for name, value in STATUS_HEX.items()}
ADD_HEX, DEL_HEX, GREY_HEX = STATUS_HEX["GREEN"], STATUS_HEX["RED"], "#9A9A9A"
GREY = colors.HexColor(GREY_HEX)
ARROW = f'<font name="{GLYPHS}">\u2192</font>'

#: 4 pt grid. The header and footer bands sit inside the top/bottom margins.
MARGIN = 56
TOP, BOTTOM = 72, 64
HEADER_Y, HEADER_RULE_Y = A4[1] - 40, A4[1] - 48
FOOTER_RULE_Y, FOOTER_Y = 44, 32
WIDTH = A4[0] - 2 * MARGIN

#: Truncation levels, tried in order until the document fits.
LADDER: list[dict[str, int]] = [
    {},
    {"diff_files": 8},
    {"diff_files": 3},
    {"diff_files": 0},
    {"diff_files": 0, "timeline": 60},
    {"diff_files": 0, "timeline": 25},
    {"diff_files": 0, "timeline": 10},
    {"diff_files": 0, "timeline": 10, "file_rows": 80, "change_rows": 80},
    {"diff_files": 0, "timeline": 10, "file_rows": 40, "change_rows": 40},
    {"diff_files": 0, "timeline": 10, "file_rows": 15, "change_rows": 15},
    {"diff_files": 0, "timeline": 10, "file_rows": 15, "change_rows": 15, "plan_rows": 15},
    {"diff_files": 0, "timeline": 5, "file_rows": 10, "change_rows": 10, "plan_rows": 5},
]


def _style(
    name: str,
    size: float,
    leading: float,
    font: str = FONT,
    color: Any = INK,
    space_after: float = 0,
    **extra: Any,
) -> ParagraphStyle:
    return ParagraphStyle(
        name,
        fontName=font,
        fontSize=size,
        leading=leading,
        textColor=color,
        spaceAfter=space_after,
        allowWidows=0,
        allowOrphans=0,
        **extra,
    )


# The type scale: title, H1, H2, body, small, mono. Leadings and gaps are x4.
TITLE = _style("title", 20, 24, BOLD, space_after=4)
H1 = _style("h1", 13, 16, BOLD, space_after=8, spaceBefore=12, keepWithNext=1)
H2 = _style("h2", 10, 12, BOLD, space_after=4, spaceBefore=8, keepWithNext=1)
BODY = _style("body", 8.5, 12, space_after=4)
SMALL = _style("small", 7, 8, space_after=4)
CODE = _style("code", 7, 8, MONO)
CELL = _style("cell", 8.5, 12)
CELL_R = _style("cellr", 8.5, 12, alignment=TA_RIGHT)
CELL_B = _style("cellb", 8.5, 12, BOLD)
CELL_BR = _style("cellbr", 8.5, 12, BOLD, alignment=TA_RIGHT)
PAD = 4  # cell padding, left/right; 2 top + 2 bottom keeps a row on the grid


def ellipsize(text: str, width: float, font: str = FONT, size: float = 8.5) -> str:
    """Middle-ellipsize ``text`` to fit ``width`` points: ``src/pk…/deep/mod.py``."""
    if stringWidth(text, font, size) <= width:
        return text
    keep = len(text)
    while keep > 1:
        keep -= 1
        head = text[: keep // 2]
        short = f"{head}…{text[len(text) - (keep - len(head)) :]}"
        if stringWidth(short, font, size) <= width:
            return short
    return "…"


def status_label(status: str, size: float | None = None) -> str:
    """``✓ GREEN`` / ``! YELLOW`` / ``✕ RED`` as Paragraph markup: never colour alone."""
    font, glyph = SYMBOL[status]
    sized = f' size="{size}"' if size else ""
    return f'<font name="{font}"{sized}>{glyph}</font> {status}'


def _p(text: Any, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _more(hidden: int) -> list[Any]:
    return [_p(f"+{hidden} more — see report.json", SMALL)] if hidden > 0 else []


def _table(
    header: list[str],
    rows: list[list[Any]],
    widths: list[float],
    numeric: tuple[int, ...] = (),
    paths: tuple[int, ...] = (),
    style: list[tuple[Any, ...]] = (),
) -> Table:
    """A ruled table: header repeats across pages, ``numeric`` columns align right,
    ``paths`` columns are middle-ellipsized to their cell instead of overflowing."""

    def cell(value: Any, col: int) -> Any:
        if isinstance(value, Paragraph):
            return value
        if col in paths:
            value = ellipsize(str(value), widths[col] - 2 * PAD)
        return _p(value, CELL_R if col in numeric else CELL)

    data = [[_p(h, CELL_BR if i in numeric else CELL_B) for i, h in enumerate(header)]] + [
        [cell(value, i) for i, value in enumerate(row)] for row in rows
    ]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, GREY),
                ("LINEBELOW", (0, 1), (-1, -1), 0.3, GREY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), PAD),
                ("RIGHTPADDING", (0, 0), (-1, -1), PAD),
                *style,
            ]
        )
    )
    return table


def _mark(passed: bool | None) -> Paragraph:
    if passed is None:
        return _p("n/a", CELL)
    status = "GREEN" if passed else "RED"
    font, glyph = SYMBOL[status]
    return Paragraph(
        f'<font color="{STATUS_INK[status]}"><font name="{font}" size="7">'
        f"{glyph}</font> <b>{'PASS' if passed else 'FAIL'}</b></font>",
        CELL,
    )


def banner(model: dict[str, Any]) -> Table:
    """Light status fill, dark text, a strong status edge — and the word + symbol."""
    status = model["verdict"]["status"]
    ink = colors.HexColor(STATUS_INK[status])
    table = Table(
        [
            [Paragraph(status_label(status), _style("status", 20, 24, BOLD, ink))],
            [_p(model["headline"], _style("why", 10, 12, color=INK))],
        ],
        colWidths=[WIDTH],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(STATUS_FILL[status])),
                ("LINEBEFORE", (0, 0), (0, -1), 4, STATUS[status]),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, 0), 12),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
            ]
        )
    )
    return table


def completed_at(meta: dict[str, Any]) -> str:
    """The run's recorded completion time: ``2026-10-02 19:42:07 IST (+05:30)``.

    Read from run_meta.json, never from the clock at render. A run recorded
    before ``completed_at`` existed falls back to ``started_at + wall_clock_s``.
    """
    if meta.get("completed_at"):
        when, zone = datetime.fromisoformat(meta["completed_at"]), meta.get("completed_tz")
    elif meta.get("started_at"):
        when = datetime.fromisoformat(meta["started_at"]) + timedelta(
            seconds=float(meta.get("wall_clock_s") or 0)
        )
        zone = None
    else:
        return "time not recorded"
    return stamp(when, zone)


def stamp(when: datetime, zone: str | None = None) -> str:
    """``2026-10-02 19:42:07 IST (+05:30)`` — the one timestamp format in the report."""
    when = when.replace(microsecond=0)
    offset = when.isoformat()[19:] or "+00:00"
    return f"{when:%Y-%m-%d %H:%M:%S} {zone or when.tzname() or 'UTC'} ({offset})"


# -- sections ---------------------------------------------------------------


def _summary(model: dict[str, Any], generated: str) -> list[Any]:
    meta, m, llm = model["meta"], model["metrics"], model["llm"]
    providers = (
        ", ".join(f"{p['provider']} ({p['model']}): {p['calls']} call(s)" for p in llm["providers"])
        or "none — deterministic path, no LLM calls"
    )
    facts = [
        ("Project", meta.get("repo_name")),
        (
            "Migration",
            Paragraph(
                f"{escape(str(meta.get('source_api')))} {ARROW} "
                f"{escape(str(meta.get('target_api')))}",
                CELL,
            ),
        ),
        ("Agent version", meta.get("agent_version")),
        ("Run id", meta.get("run_id")),
        (
            "Run started",
            stamp(datetime.fromisoformat(meta["started_at"]), meta.get("completed_tz"))
            if meta.get("started_at")
            else "not recorded",
        ),
        ("Run completed", completed_at(meta)),
        ("Outcome", m.get("outcome", "no metrics (run did not finish)")),
        ("Providers used", providers),
        ("Data egress", llm["egress_line"]),
    ]
    metric_rows = [
        [
            "M1 recall / precision",
            f"{m['m1_recall']:.1f}% / {m['m1_precision']:.1f}%" if m else "—",
        ],
        [
            "M2 pass rate / regressions",
            f"{m['m2_pass_rate']:.1f}% / {m['m2_regressions']}" if m else "—",
        ],
        [
            "M3 tokens / steps / cost",
            f"{m['m3_tokens']:,} / {m['m3_steps']} / ${m['m3_cost_usd']:.4f}" if m else "—",
        ],
    ]
    return [
        _p("Migration report", TITLE),
        Spacer(1, 4),
        banner(model),
        Spacer(1, 16),
        _p("Summary", H2),
        _table(["Field", "Value"], [[_p(k, CELL_B), v] for k, v in facts], [112, WIDTH - 112]),
        Spacer(1, 12),
        _p("Headline metrics", H2),
        _table(["Metric", "Value"], metric_rows, [168, WIDTH - 168], numeric=(1,)),
        Spacer(1, 8),
        _p(f"Report generated {generated}", SMALL),
    ]


def _graph_figure(graph: dict[str, Any]) -> list[Any]:
    nodes, changed = graph["nodes"], set(graph["changed"])
    if not nodes:
        return [_p("No in-repo imports to draw.")]
    g = nx.DiGraph()
    g.add_nodes_from(nodes)
    g.add_edges_from(graph["edges"])
    # Changed files first, then the most connected: the ones a reviewer needs.
    keep = sorted(nodes, key=lambda n: (n not in changed, -g.degree(n), n))[:GRAPH_NODE_CAP]
    sub = g.subgraph(keep)
    # Layered, not force-directed: dependencies on the left, importers to the
    # right, an import cycle sharing one column. Deterministic and numpy-free.
    condensed = nx.condensation(sub.reverse())
    layers = [
        sorted(n for scc in layer for n in condensed.nodes[scc]["members"])
        for layer in nx.topological_generations(condensed)
    ]
    height = 95 * mm
    drawing = Drawing(WIDTH, height)
    pos = {
        node: (
            20 + (WIDTH - 110) * col / max(len(layers) - 1, 1),
            height - 10 - (height - 20) * (row + 0.5) / len(layer),
        )
        for col, layer in enumerate(layers)
        for row, node in enumerate(layer)
    }

    def xy(node: str) -> tuple[float, float]:
        return pos[node]

    for a, b in sorted(sub.edges()):
        (x1, y1), (x2, y2) = xy(a), xy(b)
        drawing.add(Line(x1, y1, x2, y2, strokeColor=GREY, strokeWidth=0.5))
    for node in sorted(sub.nodes()):
        x, y = xy(node)
        drawing.add(
            Circle(
                x,
                y,
                3.2,
                fillColor=INK if node in changed else colors.white,
                strokeColor=INK,
                strokeWidth=0.6,
            )
        )
        drawing.add(
            String(
                x + 5, y - 2.5, node.rsplit("/", 1)[-1], fontName=FONT, fontSize=6, fillColor=INK
            )
        )
    note = f"Filled: changed by the migration. Showing {len(keep)} of {len(nodes)} files" + (
        f"; +{len(nodes) - len(keep)} more — see report.json." if len(nodes) > len(keep) else "."
    )
    return [drawing, _p(note, SMALL)]


def _repo_map(model: dict[str, Any], limits: dict[str, int]) -> list[Any]:
    files = model["files"]
    shown = files[: limits.get("file_rows", len(files))]
    return [
        _p("Repository map", H1),
        _table(
            ["File", "LOC", "Call sites", "Final status"],
            [[f["file"], f["loc"], f["sites"], f["status"]] for f in shown],
            [WIDTH - 212, 48, 64, 100],
            numeric=(1, 2),
            paths=(0,),
        ),
        *_more(len(files) - len(shown)),
        Spacer(1, 8),
        Paragraph(f"Dependency graph (importer {ARROW} imported)", H2),
        *_graph_figure(model["graph"]),
    ]


def _plan(model: dict[str, Any], limits: dict[str, int]) -> list[Any]:
    plan = model["plan"]
    batches = plan["batches"]
    shown = batches[: limits.get("plan_rows", len(batches))]
    cycles = {frozenset(c) for c in plan["cycles"]}
    rows = [
        [i, ", ".join(b), "cycle (atomic)" if frozenset(b) in cycles else ""]
        for i, b in enumerate(shown)
    ]
    return [
        _p("Plan", H1),
        _p(plan["rationale"]),
        _table(["Batch", "Files", "Note"], rows, [40, WIDTH - 124, 84], numeric=(0,)),
        *_more(len(batches) - len(shown)),
        _p(
            "Collapsed cycles: "
            + ("; ".join(" <-> ".join(c) for c in plan["cycles"]) or "none")
            + f". FR-3 violations: {plan['fr3_violations']}.",
            SMALL,
        ),
    ]


def _timeline(model: dict[str, Any], limits: dict[str, int]) -> list[Any]:
    rows = model["timeline"]
    shown = rows[: limits.get("timeline", len(rows))]
    return [
        _p("Execution timeline", H1),
        _table(
            ["Step", "Node", "What happened"],
            [[r["step"], r["node"], r["text"]] for r in shown],
            [40, 60, WIDTH - 100],
            numeric=(0,),
        ),
        *_more(len(rows) - len(shown)),
    ]


def _diff_line(line: str) -> Paragraph:
    text = escape(line).replace(" ", "&nbsp;") or "&nbsp;"
    if line.startswith("+"):
        text = f'<font color="{ADD_HEX}">{text}</font>'
    elif line.startswith("-"):
        text = f'<font color="{DEL_HEX}">{text}</font>'
    return Paragraph(text, CODE)


def _changes(model: dict[str, Any], limits: dict[str, int]) -> list[Any]:
    changes = model["changes"]
    salvaged = (
        " Salvaged from the run's git history: the run crashed before writing it."
        if model["verification"]["patch_salvaged"]
        else ""
    )
    flow: list[Any] = [
        _p("Changes", H1),
        _p(
            f"Full patch: migration.patch ({len(changes)} file(s), "
            f"+{sum(c['added'] for c in changes)} / -{sum(c['removed'] for c in changes)})."
            + salvaged
        ),
    ]
    if not changes:
        return [*flow, _p("No changes.")]
    flow += [
        _table(
            ["File", "+", "\u2013", "Sites"],
            [
                [
                    c["file"],
                    Paragraph(f'<font color="{ADD_HEX}">+{c["added"]}</font>', CELL_R),
                    Paragraph(f'<font color="{DEL_HEX}">\u2013{c["removed"]}</font>', CELL_R),
                    c["sites"],
                ]
                for c in changes[: limits.get("change_rows", len(changes))]
            ],
            [WIDTH - 152, 44, 44, 64],
            numeric=(1, 2, 3),
            paths=(0,),
        ),
    ]
    if (hidden := len(changes) - limits.get("change_rows", len(changes))) > 0:
        flow.append(_p(f"+{hidden} more file(s) — see migration.patch", SMALL))
    excerpted = changes[: limits.get("diff_files", len(changes))]
    for change in excerpted:
        flow.append(
            KeepTogether(
                [
                    Spacer(1, 4),
                    _p(ellipsize(change["file"], WIDTH, BOLD), CELL_B),
                    *[_diff_line(line) for line in change["excerpt"]],
                ]
            )
        )
    if len(changes) > len(excerpted):
        flow += (
            _p(f"Diff excerpts: +{len(changes) - len(excerpted)} more — see report.json", SMALL),
        )
    return flow


def _verification(model: dict[str, Any]) -> list[Any]:
    v = model["verification"]
    pre, post = v["pre"], v["post"]

    def totals(r: dict[str, Any]) -> str:
        return (
            f"{r['passed']}/{r['total']} passed, {r['failed']} failed, {r['errors']} errors"
            if r.get("total") is not None
            else "not run"
        )

    cov = v["coverage"]
    cov_rows = [
        [
            f,
            f"{len(c['executed'])}/{len(c['changed'])}",
            _mark(bool(c["executed"]) or not c["changed"]),
        ]
        for f, c in sorted(cov.items())
    ][:15]
    semantic = [[c["file"], c["detail"], _mark(c["passed"])] for c in v["semantic"]][:15]
    flow: list[Any] = [
        _p("Verification", H1),
        _p(
            f"Tests before: {totals(pre)}. Tests after: {totals(post)}. "
            f"Ruff: {v['lint']['summary']}."
        ),
        _table(
            ["Check", "Result", "Evidence"],
            [[c["check"], _mark(c["passed"]), c["evidence"]] for c in v["checks"]],
            [176, 48, WIDTH - 224],
        ),
    ]
    if semantic:
        flow += [
            Spacer(1, 8),
            _table(
                ["Semantic check: file", "Detail", "Result"],
                semantic,
                [200, WIDTH - 248, 48],
                paths=(0,),
            ),
            *_more(len(v["semantic"]) - len(semantic)),
        ]
    if cov_rows:
        flow += [
            Spacer(1, 8),
            _table(
                ["Coverage: edited file", "Changed lines run", "Result"],
                cov_rows,
                [WIDTH - 160, 112, 48],
                numeric=(1,),
                paths=(0,),
            ),
            *_more(len(cov) - len(cov_rows)),
        ]
    return flow


def _metrics(model: dict[str, Any]) -> list[Any]:
    series = model["series"]["tests_per_step"]
    flow: list[Any] = [_p("Metrics", H1)]
    if series:
        drawing = Drawing(WIDTH, 60 * mm)
        plot = LinePlot()
        plot.x, plot.y, plot.width, plot.height = 30, 22, WIDTH - 50, 60 * mm - 40
        plot.data = [[(i, passed) for i, (_, passed, _) in enumerate(series)]]
        plot.lines[0].strokeColor = INK
        plot.lines[0].symbol = makeMarker("FilledCircle", size=3, fillColor=INK)
        top = max([total for _, _, total in series] + [1])
        plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = 0, top
        plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = 0, max(len(series) - 1, 1)
        # At most ~12 ticks: one label per step overprints itself on a long run.
        plot.xValueAxis.valueSteps = list(range(0, len(series), -(-len(series) // 12)))
        plot.xValueAxis.labelTextFormat = lambda i: (
            series[int(i)][0] if int(i) < len(series) else ""
        )
        for axis in (plot.xValueAxis, plot.yValueAxis):
            axis.strokeColor = GREY
            axis.labels.fontName, axis.labels.fontSize = FONT, 7
        drawing.add(plot)
        drawing.add(
            String(
                30,
                60 * mm - 10,
                "Tests passing per step (x: step, 'pre' = baseline)",
                fontName=FONT,
                fontSize=8,
            )
        )
        flow.append(drawing)
    by_role = model["series"]["tokens_by_role"]
    if by_role:
        height = 30 + 14 * len(by_role)
        drawing = Drawing(WIDTH, height)
        chart = HorizontalBarChart()
        chart.x, chart.y, chart.width, chart.height = 110, 12, WIDTH - 140, height - 26
        chart.data = [[tokens for _, tokens in by_role]]
        chart.categoryAxis.categoryNames = [label for label, _ in by_role]
        chart.bars[0].fillColor, chart.bars[0].strokeColor = INK, None
        chart.valueAxis.valueMin = 0
        for axis in (chart.categoryAxis, chart.valueAxis):
            axis.strokeColor = GREY
            axis.labels.fontName, axis.labels.fontSize = FONT, 7
        drawing.add(chart)
        drawing.add(String(0, height - 10, "Tokens by role / provider", fontName=FONT, fontSize=8))
        flow.append(drawing)
    else:
        flow.append(_p("Tokens by role / provider: no LLM calls — deterministic run, 0 tokens."))
    return flow


def _issues(model: dict[str, Any]) -> list[Any]:
    issues = model["issues"]
    if not issues:
        return [_p("Issues & residuals", H1), _p("None. Every check passed.")]
    rows = [
        [
            Paragraph(
                f'<font color="{STATUS_INK[r["level"]]}"><b>'
                f"{status_label(r['level'], 7)}</b></font>",
                CELL,
            ),
            f"{r['text']} Evidence: {r['evidence']}",
            r["action"],
        ]
        for r in issues
    ]
    fills = [
        ("BACKGROUND", (0, i), (0, i), colors.HexColor(STATUS_FILL[r["level"]]))
        for i, r in enumerate(issues, start=1)
    ]
    rest = WIDTH - 68
    return [
        _p("Issues & residuals", H1),
        _table(
            ["Level", "Issue and evidence", "Recommended action"],
            rows,
            [68, rest * 0.58, rest * 0.42],
            style=fills,
        ),
    ]


# -- assembly ---------------------------------------------------------------


def _story(model: dict[str, Any], limits: dict[str, int], generated: str) -> list[Any]:
    return [
        *_summary(model, generated),
        PageBreak(),
        *_repo_map(model, limits),
        *_plan(model, limits),
        *_timeline(model, limits),
        *_changes(model, limits),
        *_verification(model),
        *_metrics(model),
        *_issues(model),
        Spacer(1, 16),
        KeepTogether([_p("Final status", H1), banner(model)]),
    ]


class _Doc(SimpleDocTemplate):
    """Adds a PDF outline entry (bookmark) for every title, H1 and H2."""

    def afterFlowable(self, flowable: Any) -> None:
        level = {"title": 0, "h1": 0, "h2": 1}.get(
            getattr(flowable, "style", None) and flowable.style.name
        )
        if level is None:
            return
        text = flowable.getPlainText()
        key = f"s{self.seq.nextf('outline')}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=False)


def _canvas_maker(model: dict[str, Any]) -> type[Canvas]:
    """A two-pass canvas: pages are buffered, then stamped once "of Y" is known."""
    meta = model["meta"]
    status = model["verdict"]["status"]
    footer_left = f"Run {str(meta.get('run_id') or '?')[:8]} \u00b7 completed {completed_at(meta)}"

    class NumberedCanvas(Canvas):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._pages: list[dict[str, Any]] = []

        def showPage(self) -> None:
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            for page in self._pages:
                self.__dict__.update(page)
                self._chrome(len(self._pages))
                super().showPage()
            super().save()

        def _rule(self, y: float) -> None:
            self.setStrokeColor(GREY)
            self.setLineWidth(0.4)
            self.line(MARGIN, y, A4[0] - MARGIN, y)

        def _chrome(self, total: int) -> None:
            self.saveState()
            self._rule(FOOTER_RULE_Y)
            self.setFillColor(INK)
            self.setFont(FONT, 7)
            self.drawString(MARGIN, FOOTER_Y, footer_left)
            self.drawRightString(A4[0] - MARGIN, FOOTER_Y, f"Page {self._pageNumber} of {total}")
            if self._pageNumber > 1:
                self._header()
            self.restoreState()

        def _header(self) -> None:
            self._rule(HEADER_RULE_Y)
            # Right: "[✓ GREEN] · v0.2.0" — the pill, then the version.
            version = f"\u00b7 v{meta.get('agent_version') or '?'}"
            right = A4[0] - MARGIN
            self.setFont(FONT, 7)
            self.drawRightString(right, HEADER_Y, version)
            font, glyph = SYMBOL[status]
            word_w = stringWidth(status, BOLD, 7)
            glyph_w = stringWidth(glyph, font, 6.5)
            pill_w = 4 + glyph_w + 3 + word_w + 4
            pill_x = right - stringWidth(version, FONT, 7) - 4 - pill_w
            self.setFillColor(colors.HexColor(STATUS_FILL[status]))
            self.setStrokeColor(STATUS[status])
            self.setLineWidth(0.5)
            self.roundRect(pill_x, HEADER_Y - 3, pill_w, 11, 3, stroke=1, fill=1)
            self.setFillColor(colors.HexColor(STATUS_INK[status]))
            self.setFont(font, 6.5)
            self.drawString(pill_x + 4, HEADER_Y, glyph)
            self.setFont(BOLD, 7)
            self.drawString(pill_x + 4 + glyph_w + 3, HEADER_Y, status)
            # Left: "<repo> · <source> → <target>", ellipsized clear of the pill.
            room = pill_x - 8 - MARGIN
            source = str(meta.get("source_api"))
            target = ellipsize(str(meta.get("target_api")), room / 2, FONT, 7)
            left = ellipsize(f"{meta.get('repo_name') or '?'} \u00b7 {source}", room / 2, FONT, 7)
            self.setFillColor(INK)
            x = MARGIN
            for text, face in ((left + " ", FONT), ("\u2192", GLYPHS), (" " + target, FONT)):
                self.setFont(face, 7)
                self.drawString(x, HEADER_Y, text)
                x += stringWidth(text, face, 7)

    return NumberedCanvas


def _build(model: dict[str, Any], limits: dict[str, int], generated: str) -> tuple[bytes, int]:
    buffer = io.BytesIO()
    meta = model["meta"]
    run_id = meta.get("run_id") or "?"
    # The frame pads 6 pt inside the margins; offset it so text, tables and the
    # header/footer rules all share the same left and right edge.
    doc = _Doc(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN - 6,
        rightMargin=MARGIN - 6,
        topMargin=TOP - 6,
        bottomMargin=BOTTOM - 6,
        title=f"Migration report — {meta.get('repo_name') or run_id}",
        author=f"MRA v{meta.get('agent_version') or '?'}",
        subject=f"{meta.get('source_api')} -> {meta.get('target_api')}: "
        f"{model['verdict']['status']} (run {run_id})",
        keywords=", ".join(
            str(k)
            for k in (
                "migration report",
                meta.get("repo_name"),
                meta.get("source_api"),
                meta.get("target_api"),
                model["verdict"]["status"],
                run_id,
            )
        ),
        creator="mra report",
    )
    doc.build(_story(model, limits, generated), canvasmaker=_canvas_maker(model))
    return buffer.getvalue(), doc.page


def render(model: dict[str, Any], generated: str) -> tuple[bytes, int, dict[str, int]]:
    """``(pdf bytes, pages, truncation applied)`` — the first ladder level that fits."""
    for limits in LADDER:
        data, pages = _build(model, limits, generated)
        if pages <= MAX_PAGES:
            return data, pages, limits
    raise RuntimeError(f"report exceeds {MAX_PAGES} pages even at the last truncation level")
