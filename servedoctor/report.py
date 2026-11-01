"""Static HTML scoreboard and per-incident timelines. No network, no scripts."""
from __future__ import annotations

import html
import json
from pathlib import Path

from .observe import buckets, load_incident
from .scoring import score_study

ARM_LABELS = {"rules": "Threshold rules", "glimmer": "Glimmer alone", "spark": "Spark alone",
              "wonder": "Wonder alone", "glimmer_to_spark": "Glimmer → Spark",
              "glimmer_to_wonder": "Glimmer → Wonder"}


def _spark(values, width=260, height=46, color="#2a7"):
    points = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(points) < 2:
        return f'<svg width="{width}" height="{height}"></svg>'
    top = max(v for _, v in points) or 1
    n = max(len(values) - 1, 1)
    path = " ".join(f"{'M' if k == 0 else 'L'}{i / n * width:.1f},{height - 2 - v / top * (height - 6):.1f}"
                    for k, (i, v) in enumerate(points))
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.6"/></svg>')


def render_report(study_dir, out_path=None, title="ServeIncidents scoreboard"):
    root = Path(study_dir)
    scores = score_study(root)
    answers = {a["id"]: a for a in json.loads((root / "answers" / "answer_keys.json").read_text())["answers"]}
    mode = json.loads((root / "answers" / "answer_keys.json").read_text()).get("mode", "live")
    rows = scores["rows"]
    arms = [a for a in ARM_LABELS if a in scores["by_arm"]]
    style = """body{font:14px/1.45 system-ui,sans-serif;margin:24px;color:#1b1f24;background:#fff}
table{border-collapse:collapse;margin:12px 0}td,th{border:1px solid #d0d7de;padding:4px 8px;text-align:left}
th{background:#f3f5f7}.ok{color:#116329}.bad{color:#b42318}.muted{color:#57606a}
.banner{padding:8px 12px;background:#fff4e5;border:1px solid #f0b35b;margin:8px 0}
@media (prefers-color-scheme: dark){body{background:#0d1117;color:#e6edf3}th{background:#161b22}
td,th{border-color:#30363d}.muted{color:#8b949e}.banner{background:#2d2008;border-color:#9e6a03}}"""
    parts = [f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title><style>{style}</style>",
             f"<h1>{html.escape(title)}</h1>"]
    if mode == "synthetic":
        parts.append('<div class="banner"><b>SYNTHETIC REHEARSAL.</b> Toy-model telemetry, not a result.</div>')
    parts.append("<h2>Scoreboard</h2><table><tr><th>Arm</th><th>Detected</th><th>Correct diagnosis</th>"
                 "<th>Fix proposed</th><th>Harmful actions</th><th>False alarms</th>"
                 "<th>Median time to detect</th><th>Invalid outputs</th><th>Paid Meta calls / cost</th></tr>")
    for arm in arms:
        a = scores["by_arm"][arm]
        parts.append(
            f"<tr><td>{ARM_LABELS[arm]}</td><td>{a['detected']}/{a['incidents']}</td>"
            f"<td>{a['diagnosis_correct']}/{a['incidents']}</td><td>{a['fix_proposed']}/{a['incidents']}</td>"
            f"<td>{a['harmful']}</td><td>{a['false_alarms']} ({a['healthy_false_alarms']}/{a['healthy_controls']} controls)</td>"
            f"<td>{a['median_time_to_detect_s'] if a['median_time_to_detect_s'] is not None else '–'} s</td>"
            f"<td>{a['invalid_outputs']}</td><td>{a['api_calls']} / ${a['api_cost_usd']:.3f}</td></tr>")
    parts.append("</table><p class=muted>Incidents exclude healthy controls. Diagnosis on a control counts as "
                 "correct only if nothing is flagged. Fixes are judged against sealed per-cause rules.</p>")
    parts.append("<h2>Incidents</h2><table><tr><th>Incident</th><th>Split</th><th>Truth</th>"
                 "<th>p95 latency</th><th>arrivals/s</th>" + "".join(f"<th>{ARM_LABELS[a]}</th>" for a in arms) + "</tr>")
    by_incident = {}
    for row in rows:
        by_incident.setdefault(row["incident"], {})[row["arm"]] = row
    for incident_id in sorted(by_incident):
        answer = answers[incident_id]
        path = root / "incidents" / incident_id
        series = buckets(load_incident(path)["telemetry"], float("inf")) if path.exists() else []
        cells = []
        for arm in arms:
            row = by_incident[incident_id].get(arm)
            if row is None:
                cells.append("<td>–</td>")
                continue
            ok = row["diagnosis_correct"] and not row["harmful"] and not row["false_alarm"]
            label = row["predicted"] + (f" @ {row['flag_t']}s" if row["flagged"] else "")
            if row["harmful"]:
                label += " · harmful"
            cells.append(f'<td class="{"ok" if ok else "bad"}">{html.escape(label)}</td>')
        parts.append(f"<tr><td>{incident_id}</td><td>{answer['split']}</td><td>{answer['root_cause']} "
                     f"<span class=muted>(sev {answer['severity_index']})</span></td>"
                     f"<td>{_spark([b['p95_latency_s'] for b in series], color='#c4432b')}</td>"
                     f"<td>{_spark([b['arrivals_rps'] for b in series])}</td>{''.join(cells)}</tr>")
    parts.append("</table>")
    out = Path(out_path or root / "report.html")
    out.write_text("\n".join(parts))
    (out.with_suffix(".json")).write_text(json.dumps(scores, indent=1, default=str))
    return out
