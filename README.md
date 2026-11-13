# Model Hub

One page on your phone with the latest results from every model you run on your Mac.

- **Site:** `index.html` + `app.js` (no build step, no libraries). Save it to your home screen and it opens like an app, and still opens offline with the last results it loaded.
- **Results:** `data/<model>.json`, one file per model. `data/index.json` is the list the home screen reads. `hub.py` writes both for you.
- **Sending results:** `hub.py` (Python standard library only). It writes the files, commits and pushes. GitHub Pages updates in under a minute.

Everything here is free: GitHub Pages on a public repo, no paid services, no API keys.

## One-time setup on the Mac

```
brew install gh
gh auth login
gh repo clone hpjoplin/model-hub ~/model-hub
```

`gh auth login` signs git in to GitHub so pushes just work. (No Homebrew? Clone with `git clone https://github.com/hpjoplin/model-hub.git ~/model-hub`; the first push asks for your GitHub user name and a personal access token as the password, and macOS remembers it.)

## Sending results

### HTML reports (what your models make now)

Add this one line to the end of a model's Python script, with that model's id, name and the HTML file it writes:

```
import subprocess, os; subprocess.run(["python3", os.path.expanduser("~/model-hub/hub.py"), "publish", "cfb_edge", "cfb_card.html", "--name", "CFB Edge"])
```

Or from the Terminal:

```
python3 ~/model-hub/hub.py publish cfb_edge cfb_card.html --name "CFB Edge"
```

The report shows inside the app, newest first, with the last 10 kept to flip back through. Anything in it that looks like an API key, token or password is blanked before it's sent. One self-contained HTML file works best: if the report loads a separate .css file or images from its own folder, those won't come along.

### Tables (CSV or JSON)

From the Terminal, after a model run:

```
python3 ~/model-hub/hub.py publish cfb_edge ~/path/to/card.csv --name "CFB Edge" --sport "College football" --headline "Week 12 card" --stat "Record=34-21"
```

Or at the end of a model's own Python script (rows can be a list of dicts or a pandas DataFrame):

```
import sys, os; sys.path.insert(0, os.path.expanduser("~/model-hub"))
import hub
hub.publish("cfb_edge", rows, name="CFB Edge", sport="College football",
            headline="Week 12 card", stats={"Record": "34-21", "ROI": "+6.2%"})
```

Other commands:

```
python3 ~/model-hub/hub.py list            # what's on the site
python3 ~/model-hub/hub.py remove cfb_edge # take a model off
```

The first real publish removes the "Example model" sample card.

### Columns the phone page understands

Any columns work; these just get nicer placement:

| Column name | Shows as |
|---|---|
| `title`, `game`, `matchup`, `event`, `race`, `market` | bold first line |
| `pick`, `bet`, `selection`, `prediction` | highlighted pick |
| `edge`, `ev`, `value`, `overlay` | green when positive, red when negative |
| `note`, `reason` | small text under the row |
| `result`, `status` | green for W / win / hit, red for L / loss / miss |
| names with `prob` or `win%`, values 0 to 1 | a percent |

## Privacy

The repo is public so GitHub Pages stays free. Anyone with the link can see the site and every results file you send, including older versions in the repo history. `hub.py` leaves out any column whose name looks like a key, token or password, but don't send anything you wouldn't want seen.

## On the phone

Open https://hpjoplin.github.io/model-hub/ in Safari, tap Share, then **Add to Home Screen**.
