#!/usr/bin/env python3
"""
hub.py: send a model's results to Model Hub (your phone site).

It lives in your local copy of the model-hub repo. Nothing to install:
standard library only, works with the python3 that comes with macOS.

From the Terminal:
    python3 ~/model-hub/hub.py publish cfb_edge report.html --name "CFB Edge" --sport "College football"
    python3 ~/model-hub/hub.py publish cfb_edge picks.csv --name "CFB Edge" --sport "College football"
    python3 ~/model-hub/hub.py publish diamond_edge out.json --headline "Tonight's slate" --stat "Record=41-30"
    python3 ~/model-hub/hub.py list
    python3 ~/model-hub/hub.py remove cfb_edge

From inside a model's own Python code (rows can be a list of dicts or a pandas DataFrame):
    import sys, os; sys.path.insert(0, os.path.expanduser("~/model-hub"))
    import hub
    hub.publish("cfb_edge", rows, name="CFB Edge", sport="College football",
                headline="Week 12 card", stats={"Record": "34-21", "ROI": "+6.2%"})

An .html file is copied into reports/<id>/ (the last 10 are kept) and shown inside
the app; anything that looks like an API key, token or password in it is blanked out.
Works best when the HTML is one self-contained file (styles and charts inside it).

Each publish writes data/<id>.json, rebuilds data/index.json, then commits and
pushes to GitHub so the phone site shows it a few seconds later.
Pass --no-push (or push=False) to only write the files.

Column names that make the phone page look nicer (all optional, any others show as small tags):
    title / game / matchup / event / race / market   -> bold first line
    pick / bet / selection / prediction               -> highlighted pick
    edge / ev / value / overlay                       -> green if positive, red if negative
    note / reason                                     -> small text under the row
    result / status                                   -> green for W/win/hit, red for L/loss/miss
    anything with "prob" or "win%" in its name, 0 to 1 -> shown as a percent
"""
import argparse
import csv
import datetime as _dt
import json
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
REPORTS = os.path.join(HERE, "reports")
KEEP_REPORTS = 10
MAX_ROWS = 2000
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# Columns that look like secrets never get published, because the site is public.
SECRET_RE = re.compile(r"(api[_-]?key|secret|token|password|passwd|private[_-]?key|auth|cookie|session)", re.I)


# Things in an HTML report that look like credentials get blanked before it goes public.
_SECRET_PATTERNS = [
    # key = "value", "token": "value", api_key=value in a URL, etc.
    (re.compile(r'((?:api[_-]?key|apikey|access[_-]?key|secret|token|password|passwd|authorization|x-api-key)'
                r'["\']?\s*[:=]\s*["\']?)([^"\'\s&,;<>)]{8,})', re.I), r"\1[removed]"),
    (re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}"), "[removed]"),          # OpenAI / Anthropic style keys
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.I), "Bearer [removed]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}"), "[removed]"),  # GitHub tokens
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[removed]"),                      # AWS access key ids
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[removed]"),             # Slack tokens
]


def scrub_html(text):
    """Blank out anything that looks like a key, token or password. Returns (text, count)."""
    total = 0
    for rx, repl in _SECRET_PATTERNS:
        text, n = rx.subn(repl, text)
        total += n
    return text, total


def _html_title(text):
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if not m:
        return ""
    t = re.sub(r"<[^>]+>", "", m.group(1))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:80]


def _save_report(model_id, report, stamp):
    """Copy an HTML report (a path or the HTML text) into reports/<id>/. Returns (relative path, title)."""
    if os.path.exists(str(report)) and os.path.isfile(str(report)):
        with open(report, encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        text = str(report)
    text, n = scrub_html(text)
    if n:
        print("hub: blanked %d thing(s) in the report that looked like keys or passwords" % n, file=sys.stderr)
    folder = os.path.join(REPORTS, model_id)
    os.makedirs(folder, exist_ok=True)
    fn = re.sub(r"[^0-9]", "", stamp)[:14] + ".html"
    with open(os.path.join(folder, fn), "w", encoding="utf-8") as f:
        f.write(text)
    return "reports/%s/%s" % (model_id, fn), _html_title(text)


def _prune_reports(model_id, keep):
    folder = os.path.join(REPORTS, model_id)
    if not os.path.isdir(folder):
        return
    keep_names = set(os.path.basename(k) for k in keep)
    for fn in os.listdir(folder):
        if fn.endswith(".html") and fn not in keep_names:
            os.remove(os.path.join(folder, fn))


def _now():
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_value(v):
    """Turn numpy/pandas values and NaN into plain JSON values."""
    if v is None:
        return None
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):  # numpy scalar
        try:
            v = v.item()
        except Exception:
            pass
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (list, tuple)):
        return [_clean_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _clean_value(x) for k, x in v.items()}
    return str(v)


def _parse_cell(s):
    """CSV cells come in as text; turn numbers back into numbers."""
    if s is None:
        return None
    t = s.strip()
    if t == "":
        return None
    if re.fullmatch(r"[+-]?\d+", t) and not (len(t) > 1 and t.lstrip("+-").startswith("0")):
        try:
            return int(t)
        except ValueError:
            pass
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?", t):
        try:
            return float(t)
        except ValueError:
            pass
    return t


def _to_rows(rows):
    if rows is None:
        return []
    if hasattr(rows, "to_dict"):  # pandas DataFrame
        rows = rows.to_dict(orient="records")
    out = []
    dropped = set()
    for r in list(rows)[:MAX_ROWS]:
        if isinstance(r, dict):
            clean = {}
            for k, v in r.items():
                k = str(k)
                if SECRET_RE.search(k):
                    dropped.add(k)
                    continue
                v = _clean_value(v)
                if v is None or v == "":
                    continue
                clean[k] = v
            out.append(clean)
        else:
            out.append(_clean_value(r))
    if dropped:
        print("hub: left out columns that look private: " + ", ".join(sorted(dropped)), file=sys.stderr)
    if hasattr(rows, "__len__") and len(rows) > MAX_ROWS:
        print("hub: kept the first %d rows of %d" % (MAX_ROWS, len(rows)), file=sys.stderr)
    return out


def _stats_list(stats):
    if not stats:
        return []
    if isinstance(stats, dict):
        stats = [{"label": k, "value": v} for k, v in stats.items()]
    out = []
    for s in stats:
        if isinstance(s, dict) and "label" in s:
            item = {"label": str(s["label"]), "value": _clean_value(s.get("value"))}
            if s.get("tone") in ("pos", "neg"):
                item["tone"] = s["tone"]
            out.append(item)
    return out


def _read_file(path):
    """Read a .csv or .json results file. Returns (rows, extra_fields)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [{k: _parse_cell(v) for k, v in row.items() if k is not None} for row in csv.DictReader(f)], {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data, {}
    if isinstance(data, dict):
        rows = data.get("rows") or data.get("picks") or data.get("results") or []
        extra = {k: data[k] for k in ("name", "sport", "headline", "stats", "updated") if k in data}
        return rows, extra
    raise SystemExit("hub: %s should hold a list of rows or an object with a 'rows' list" % path)


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def rebuild_index():
    models = []
    for fn in sorted(os.listdir(DATA)):
        if not fn.endswith(".json") or fn == "index.json":
            continue
        try:
            with open(os.path.join(DATA, fn), encoding="utf-8") as f:
                m = json.load(f)
        except Exception as e:
            print("hub: skipped %s (%s)" % (fn, e), file=sys.stderr)
            continue
        entry = {
            "id": m.get("id", fn[:-5]),
            "file": fn,
            "name": m.get("name") or m.get("id", fn[:-5]),
            "sport": m.get("sport", ""),
            "headline": m.get("headline", ""),
            "updated": m.get("updated", ""),
            "count": len(m.get("rows") or []),
        }
        if m.get("reports"):
            entry["report"] = m["reports"][0]["file"]
            entry["report_count"] = len(m["reports"])
        if m.get("demo"):
            entry["demo"] = True
        models.append(entry)
    _write_json(os.path.join(DATA, "index.json"), {"updated": _now(), "models": models})
    return models


def _git(*args, check=True):
    return subprocess.run(["git", "-C", HERE] + list(args), check=check, capture_output=True, text=True)


def push(message):
    """Commit data/ and push it to GitHub."""
    try:
        _git("add", "-A", "data", "reports")
        if _git("diff", "--cached", "--quiet", check=False).returncode == 0:
            print("hub: nothing new to send")
            return
        _git("commit", "-q", "-m", message)
        pull = _git("pull", "--rebase", "--autostash", "-q", check=False)
        if pull.returncode != 0:
            _git("rebase", "--abort", check=False)
            print("hub: couldn't pull first (%s); pushing anyway" % pull.stderr.strip(), file=sys.stderr)
        _git("push", "-q")
        print("hub: sent. Your phone will show it after a refresh.")
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or e.stdout or str(e)).strip()
        raise SystemExit("hub: git step failed: " + msg)


def _remove_demo_files():
    for fn in os.listdir(DATA):
        if fn.endswith(".json") and fn != "index.json":
            p = os.path.join(DATA, fn)
            try:
                with open(p, encoding="utf-8") as f:
                    if json.load(f).get("demo"):
                        os.remove(p)
                        print("hub: removed sample model %s" % fn[:-5])
            except Exception:
                pass


def publish(model_id, rows=None, name=None, sport=None, headline=None, stats=None, updated=None,
            push_to_github=True, report=None, **_):
    """Write one model's results and (by default) push them. Returns the saved object.
    rows: list of dicts or a DataFrame. report: an .html file path, or HTML text."""
    model_id = str(model_id).strip().lower().replace(" ", "_")
    if not ID_RE.match(model_id):
        raise SystemExit("hub: model id should be letters, numbers, - or _ (got %r)" % model_id)
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, model_id + ".json")
    old = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            old = {}
    stamp = updated or _now()
    reports = list(old.get("reports") or [])
    title = ""
    if report is not None:
        rel, title = _save_report(model_id, report, stamp)
        reports = [r for r in reports if r.get("file") != rel]
        reports.insert(0, {"file": rel, "updated": stamp, "title": title})
        reports = reports[:KEEP_REPORTS]
        _prune_reports(model_id, [r["file"] for r in reports])
        if rows is None:
            rows = []
    obj = {
        "id": model_id,
        "name": name or old.get("name") or title or model_id.replace("_", " ").title(),
        "sport": sport if sport is not None else old.get("sport", ""),
        "headline": headline if headline is not None else "",
        "updated": stamp,
        "stats": _stats_list(stats),
        "rows": _to_rows(rows),
    }
    if reports:
        obj["reports"] = reports
    _remove_demo_files()
    _write_json(path, obj)
    rebuild_index()
    print("hub: saved %s (%s)" % (model_id, "report" if report is not None else "%d rows" % len(obj["rows"])))
    if push_to_github:
        push("Update %s results" % model_id)
    return obj


def remove(model_id, push_to_github=True):
    path = os.path.join(DATA, model_id + ".json")
    if not os.path.exists(path):
        raise SystemExit("hub: no model called %s" % model_id)
    os.remove(path)
    folder = os.path.join(REPORTS, model_id)
    if os.path.isdir(folder):
        import shutil
        shutil.rmtree(folder)
    rebuild_index()
    print("hub: removed %s" % model_id)
    if push_to_github:
        push("Remove %s" % model_id)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Send model results to Model Hub.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("publish", help="send one model's results")
    p.add_argument("id", help="short id, like cfb_edge")
    p.add_argument("file", help="an .html report, or a .csv or .json results file")
    p.add_argument("--name", help="name shown on the phone, like 'CFB Edge'")
    p.add_argument("--sport", help="like 'College football'")
    p.add_argument("--headline", help="one line under the name, like 'Week 12 card'")
    p.add_argument("--stat", action="append", default=[], metavar="LABEL=VALUE", help="a number tile; repeat for more")
    p.add_argument("--no-push", action="store_true", help="write the files but don't send them")

    r = sub.add_parser("remove", help="take a model off the site")
    r.add_argument("id")
    r.add_argument("--no-push", action="store_true")

    sub.add_parser("list", help="show what's on the site")
    sub.add_parser("push", help="send whatever is in data/ now")

    a = ap.parse_args(argv)
    if a.cmd == "publish":
        if not os.path.isfile(a.file):
            raise SystemExit("hub: can't find %s" % a.file)
        is_html = os.path.splitext(a.file)[1].lower() in (".html", ".htm")
        rows, extra = (None, {}) if is_html else _read_file(a.file)
        stats = extra.get("stats")
        if a.stat:
            stats = []
            for s in a.stat:
                if "=" not in s:
                    raise SystemExit("hub: --stat should look like Label=Value")
                k, v = s.split("=", 1)
                stats.append({"label": k.strip(), "value": _parse_cell(v)})
        publish(a.id, rows,
                name=a.name or extra.get("name"),
                sport=a.sport if a.sport is not None else extra.get("sport"),
                headline=a.headline if a.headline is not None else extra.get("headline"),
                stats=stats, updated=extra.get("updated"),
                report=a.file if is_html else None,
                push_to_github=not a.no_push)
    elif a.cmd == "remove":
        remove(a.id, push_to_github=not a.no_push)
    elif a.cmd == "list":
        for m in rebuild_index():
            what = ("%d reports" % m["report_count"]) if m.get("report") else ("%d rows" % m["count"])
            print("%-20s %-22s %10s  %s%s" % (m["id"], m["name"][:22], what, m["updated"], "  (sample)" if m.get("demo") else ""))
    elif a.cmd == "push":
        rebuild_index()
        push("Update results")


if __name__ == "__main__":
    main()
