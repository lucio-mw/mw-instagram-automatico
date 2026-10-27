#!/usr/bin/env python3
"""Gera fila.html: o próximo post em destaque, o que já saiu hoje e a fila
completa (reels às 9h/19h, carrosséis às 12h na data do nome).

Uso: python3 gerar_fila_html.py   (rode depois de um git pull)
"""

import base64
import html
import re
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POSTS = ROOT / "posts"
OUT = ROOT / "fila.html"
REEL_HOURS = ("09:00", "19:00")
CAROUSEL_HOUR = "12:00"
WEEKDAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def thumb(source, width, seek=None):
    """Miniatura JPEG em base64 (frame do vídeo ou imagem reduzida)."""
    with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        if seek is not None:
            cmd += ["-ss", str(seek)]
        cmd += ["-i", str(source), "-frames:v", "1", "-vf", f"scale={width}:-1", "-q:v", "5", tmp.name]
        subprocess.run(cmd, check=True)
        return base64.b64encode(Path(tmp.name).read_bytes()).decode()


def title(folder):
    return re.sub(r"^\d{4}-\d\d-\d\d-|^\d+-", "", folder.name).replace("-", " ")


def caption(folder):
    return (folder / "legenda.txt").read_text(encoding="utf-8").strip()


def queued(queue):
    folder = POSTS / queue
    return [p for p in folder.iterdir() if p.is_dir() and p.name != "publicados"] if folder.exists() else []


def schedule(now):
    """Lista (quando, tipo, pasta) da fila, em ordem."""
    reels = sorted(queued("reels"), key=lambda p: int(re.match(r"\d+", p.name).group()))
    slots = []
    day = now.date()
    while len(slots) < len(reels):
        for hour in REEL_HOURS:
            when = datetime.combine(day, datetime.strptime(hour, "%H:%M").time())
            if when > now:
                slots.append(when)
        day += timedelta(days=1)
    items = [(when, "Reel", reel) for when, reel in zip(slots, reels)]
    noon = datetime.strptime(CAROUSEL_HOUR, "%H:%M").time()
    for folder in queued("carrosseis"):
        y, m, d = map(int, folder.name[:10].split("-"))
        when = datetime.combine(date(y, m, d), noon)
        if when <= now:  # atrasado: sai na próxima rodada
            when = now
        items.append((when, "Carrossel", folder))
    return sorted(items, key=lambda item: item[0])


def published_today(today):
    done = []
    for record in POSTS.glob("*/publicados/*.txt"):
        text = record.read_text(encoding="utf-8")
        match = re.search(r"horario: (\S+ \S+)", text)
        if match and match.group(1).startswith(today.isoformat()):
            done.append((match.group(1)[11:], record.parent.parent.name, record.stem))
    return sorted(done)


def card(when, kind, folder):
    if kind == "Reel":
        img = thumb(folder / "video.mp4", 180, seek=3)
        track = (folder / "audio.txt").read_text().strip() if (folder / "audio.txt").exists() else ""
        meta = "trilha " + re.sub(r"^\d+-|\.m4a$", "", track).replace("-", " ") if track else "sem trilha"
    else:
        img = thumb(sorted(folder.glob("slide-*.jpg"))[0], 180)
        meta = f"{len(list(folder.glob('slide-*.jpg')))} slides"
    text = caption(folder)
    return (
        f'<article class="{kind.lower()}"><img src="data:image/jpeg;base64,{img}" alt="" loading="lazy">'
        f'<div class="body"><div class="top"><span class="time">{when:%H:%M}</span>'
        f'<span class="kind">{kind}</span></div><div class="name">{html.escape(title(folder))}</div>'
        f'<div class="meta">{html.escape(meta)}</div><p>{html.escape(text.splitlines()[0])}</p>'
        f'<details><summary>Legenda completa</summary><pre>{html.escape(text)}</pre></details></div></article>'
    )


def featured(when, kind, folder, now):
    if kind == "Reel":
        media = f'<img src="data:image/jpeg;base64,{thumb(folder / "video.mp4", 360, seek=3)}" alt="">'
    else:
        media = "".join(
            f'<img src="data:image/jpeg;base64,{thumb(slide, 440)}" alt="Slide {i}">'
            for i, slide in enumerate(sorted(folder.glob("slide-*.jpg")), 1)
        )
    day = "Hoje" if when.date() == now.date() else f"{WEEKDAYS[when.weekday()]}, {when:%d/%m}"
    return (
        f'<section class="feat"><div class="feat-head"><span class="badge">Próximo post</span>'
        f"<b>{day}, {when:%H:%M}</b> · {kind} · {html.escape(title(folder))}</div>"
        f'<div class="strip">{media}</div><pre class="cap">{html.escape(caption(folder))}</pre></section>'
    )


CSS = """
:root{--bg:#f7f6f2;--card:#fff;--fg:#141414;--muted:#6b6b6b;--line:#e6e3dc;--gold:#a8842f;--reel:#2f5d8a}
@media (prefers-color-scheme:dark){:root{--bg:#0d0d0d;--card:#171717;--fg:#f2f2f2;--muted:#a0a0a0;--line:#2a2a2a;--gold:#d4b062;--reel:#7fb0e0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,BlinkMacSystemFont,sans-serif;padding:24px 16px}
.wrap{max-width:900px;margin:0 auto}h1{font-size:22px;margin:0}.lead{color:var(--muted);margin:4px 0 8px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:26px 0 10px}
.row{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px}
article{display:flex;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}
article img{width:72px;height:auto;align-self:flex-start;border-radius:6px}
.body{min-width:0;flex:1}.top{display:flex;gap:8px;align-items:center}.time{font-weight:700;font-variant-numeric:tabular-nums}
.kind{font-size:11px;padding:1px 7px;border-radius:99px;border:1px solid currentColor}.reel .kind{color:var(--reel)}.carrossel .kind{color:var(--gold)}
.name{font-weight:600;margin-top:3px}.name::first-letter{text-transform:uppercase}.meta{font-size:12px;color:var(--muted)}
p{margin:6px 0 4px;font-size:13px}details summary{cursor:pointer;color:var(--muted);font-size:12px}
pre{white-space:pre-wrap;font:12px/1.45 -apple-system,sans-serif;margin:6px 0 0;color:var(--muted)}
.feat{background:var(--card);border:1px solid var(--gold);border-radius:12px;padding:14px;margin:18px 0 6px}
.feat-head{font-size:14px;margin-bottom:10px}.feat-head b::first-letter{text-transform:uppercase}
.badge{background:var(--gold);color:#fff;font-size:11px;font-weight:700;padding:2px 8px;border-radius:99px;margin-right:8px;text-transform:uppercase;letter-spacing:.05em}
.strip{display:flex;gap:8px;overflow-x:auto;padding-bottom:6px}.strip img{width:220px;flex:0 0 auto;border-radius:8px}
.cap{color:var(--fg);font-size:13px;margin-top:10px}.done{color:var(--muted);font-size:13px;margin:6px 0 0}
"""


def main():
    now = datetime.now()
    items = schedule(now)
    parts = []
    if items:
        parts.append(featured(*items[0], now))
    for hour, queue, name in published_today(now.date()):
        kind = "Reel" if queue == "reels" else "Carrossel"
        label = re.sub(r"^\d{4}-\d\d-\d\d-|^\d+-", "", name).replace("-", " ")
        parts.append(f'<p class="done">✅ Hoje às {hour}: {kind}, {html.escape(label)} (já publicado)</p>')
    current = None
    for when, kind, folder in items:
        if when.date() != current:
            if current:
                parts.append("</div>")
            current = when.date()
            today = " · hoje" if current == now.date() else ""
            parts.append(f'<h2>{WEEKDAYS[current.weekday()]}, {current:%d/%m}{today}</h2><div class="row">')
        parts.append(card(when, kind, folder))
    if current:
        parts.append("</div>")

    reels = sum(1 for item in items if item[1] == "Reel")
    end = f"até {items[-1][0]:%d/%m}" if items else "vazia"
    lead = (
        f"{len(items)} posts na fila ({reels} Reels e {len(items) - reels} carrosséis), {end}. "
        f"Reels às 9h e 19h; carrossel às 12h na data do nome. Atualizado em {now:%d/%m às %H:%M}."
    )
    OUT.write_text(
        '<!doctype html><html lang="pt-br"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Fila de posts</title>'
        f'<style>{CSS}</style></head><body><div class="wrap"><h1>Fila de posts · @mwcapital.inc</h1>'
        f'<p class="lead">{lead}</p>{"".join(parts)}</div></body></html>',
        encoding="utf-8",
    )
    print(f"{OUT.name}: {lead}")


if __name__ == "__main__":
    main()
