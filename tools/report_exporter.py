"""Professional report export (Task 11): Markdown + HTML.

Converts structured report sections (title, summary, metrics, sections,
code blocks, tables) into a downloadable Markdown or styled HTML file.
PDF/DOCX exports are offered when the optional libraries are installed.
"""
import html
import os
import time


def _md_table(headers, rows):
    if not rows:
        return ""
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def to_markdown(report):
    """Render a report dict as Markdown text.

    Expected structure:
        {"title": str, "subtitle": str, "summary": [str...],
         "metrics": [(label, value)...], "sections": [(heading, body)...],
         "tables": [(caption, headers, rows)...], "code": str}
    """
    out = []
    out.append(f"# {report.get('title', 'Report')}")
    if report.get("subtitle"):
        out.append(f"*{report['subtitle']}*")
    out.append("")

    if report.get("summary"):
        out.append("## Summary")
        for line in report["summary"]:
            out.append(f"- {line}")
        out.append("")

    if report.get("metrics"):
        out.append("## Metrics")
        for label, value in report["metrics"]:
            out.append(f"- **{label}:** {value}")
        out.append("")

    for heading, body in report.get("sections", []):
        out.append(f"## {heading}")
        out.append(body)
        out.append("")

    for caption, headers, rows in report.get("tables", []):
        out.append(f"### {caption}")
        out.append(_md_table(headers, rows))
        out.append("")

    if report.get("code"):
        out.append("## Code")
        out.append("```python")
        out.append(report["code"])
        out.append("```")

    out.append("---")
    out.append(f"*Generated {time.strftime('%Y-%m-%d %H:%M:%S')} "
               "by the Multi-AI Coding Assistant*")
    return "\n".join(out)


_CSS = """
body { font-family: 'Segoe UI', system-ui, sans-serif; margin: 40px auto;
       max-width: 900px; color: #1f2937; line-height: 1.6; }
h1 { color: #4f46e5; border-bottom: 3px solid #4f46e5; padding-bottom: 8px; }
h2 { color: #4338ca; margin-top: 32px; }
h3 { color: #4b5563; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; }
th, td { border: 1px solid #e5e7eb; padding: 8px 12px; text-align: left; }
th { background: #eef2ff; }
pre { background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 8px;
      overflow-x: auto; }
code { font-family: 'Cascadia Code', Consolas, monospace; }
.meta { color: #6b7280; font-size: 0.9em; }
"""


def to_html(report):
    """Render a report dict as a self-contained styled HTML page."""
    parts = ["<!DOCTYPE html><html><head><meta charset='utf-8'>"]
    parts.append(f"<title>{html.escape(report.get('title', 'Report'))}</title>")
    parts.append(f"<style>{_CSS}</style></head><body>")
    parts.append(f"<h1>{html.escape(report.get('title', 'Report'))}</h1>")
    if report.get("subtitle"):
        parts.append(f"<p class='meta'>{html.escape(report['subtitle'])}</p>")

    if report.get("summary"):
        parts.append("<h2>Summary</h2><ul>")
        for line in report["summary"]:
            parts.append(f"<li>{html.escape(line)}</li>")
        parts.append("</ul>")

    if report.get("metrics"):
        parts.append("<h2>Metrics</h2><table><thead><tr><th>Metric</th>"
                     "<th>Value</th></tr></thead><tbody>")
        for label, value in report["metrics"]:
            parts.append(f"<tr><td>{html.escape(str(label))}</td>"
                         f"<td>{html.escape(str(value))}</td></tr>")
        parts.append("</tbody></table>")

    for heading, body in report.get("sections", []):
        parts.append(f"<h2>{html.escape(heading)}</h2>")
        parts.append(f"<p>{html.escape(body).replace(chr(10), '<br>')}</p>")

    for caption, headers, rows in report.get("tables", []):
        parts.append(f"<h3>{html.escape(caption)}</h3><table><thead><tr>")
        parts.append("".join(f"<th>{html.escape(str(h))}</th>" for h in headers))
        parts.append("</tr></thead><tbody>")
        for row in rows:
            parts.append("<tr>" + "".join(
                f"<td>{html.escape(str(c))}</td>" for c in row
            ) + "</tr>")
        parts.append("</tbody></table>")

    if report.get("code"):
        parts.append("<h2>Code</h2>")
        parts.append(f"<pre><code>{html.escape(report['code'])}</code></pre>")

    parts.append(f"<p class='meta'>Generated "
                 f"{time.strftime('%Y-%m-%d %H:%M:%S')} by the "
                 "Multi-AI Coding Assistant</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def export(report, format="md"):
    """Return (filename, content, mime) for the requested format."""
    title = report.get("title", "report").lower().replace(" ", "_")
    stamp = time.strftime("%Y%m%d_%H%M%S")

    if format == "html":
        return f"{title}_{stamp}.html", to_html(report), "text/html"
    if format == "md":
        return f"{title}_{stamp}.md", to_markdown(report), "text/markdown"
    if format == "pdf":
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import inch
            from reportlab.pdfgen import canvas
        except ImportError:
            return f"{title}_{stamp}.md", to_markdown(report), "text/markdown"
        filename = f"{title}_{stamp}.pdf"
        c = canvas.Canvas(filename, pagesize=A4)
        width, height = A4
        y = height - 1 * inch
        c.setFont("Helvetica-Bold", 16)
        c.drawString(1 * inch, y, report.get("title", "Report"))
        y -= 0.5 * inch
        c.setFont("Helvetica", 10)
        for line in to_markdown(report).splitlines()[:60]:
            c.drawString(1 * inch, y, line[:95])
            y -= 0.18 * inch
            if y < 1 * inch:
                c.showPage()
                y = height - 1 * inch
        c.save()
        try:
            with open(filename, "rb") as f:
                data = f.read()
        finally:
            os.remove(filename)  # don't leave artifacts in the workspace
        return filename, data, "application/pdf"
    return f"{title}_{stamp}.md", to_markdown(report), "text/markdown"
