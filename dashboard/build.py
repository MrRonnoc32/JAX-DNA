"""Build the single-file dashboard by injecting export.json into the template."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def build_dashboard(export_path, out_path):
    with open(export_path, encoding="utf-8") as f:
        data = json.load(f)
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        tpl = f.read()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace("/*__DATA__*/null", payload)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[dashboard] wrote {out_path}")
    return out_path
