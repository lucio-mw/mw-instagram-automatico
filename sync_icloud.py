#!/usr/bin/env python3
"""Sincroniza as pastas de conteúdo do iCloud com a fila de posts no GitHub.

Roda no Mac (agendado pelo launchd, ver instalar_mac.sh). A cada execução:
  1. baixa do GitHub o que já foi publicado (git pull);
  2. marca no iCloud o que foi publicado:
       carrosséis -> move para Carrosseis Claude/Postados/Postado-<nome>
       reels      -> renomeia para Postagem Diaria Instagram/Postado-<nome>
  3. copia para posts/ os conteúdos novos e prontos, e envia ao GitHub;
  4. se um horário da agenda venceu sem post, dispara a publicação no GitHub
     (o agendador do próprio GitHub atrasa horas e fica só como reserva).
     Nos reels, coloca de fundo uma das trilhas da pasta "Audios Reels".

Um conteúdo é considerado pronto quando tem legenda.txt, a mídia e nenhum
arquivo foi alterado nos últimos minutos (para não pegar pela metade um
carrossel que ainda está sendo gerado).
"""

import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "posts"
INSTAGRAM_DIR = (
    Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Documentos MW Capital/Instagram"
)
CAROUSELS_SRC = INSTAGRAM_DIR / "Carrosseis Claude"
REELS_SRC = INSTAGRAM_DIR / "Postagem Diaria Instagram"
# Trilhas livres de direitos que vão de fundo nos reels (alternadas entre eles).
# Pasta vazia ou inexistente = reels publicados sem áudio.
AUDIO_SRC = INSTAGRAM_DIR / "Audios Reels"
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac"}
AUDIO_MARKER = "audio.txt"
CAPTION_FILE = "legenda.txt"
POSTED_PREFIX = "Postado-"
READY_AFTER_SECONDS = 5 * 60
MAX_CAPTION = 2200
MAX_HASHTAGS = 30
MAX_CAROUSEL = 10
# A API aceita imagens entre 4:5 (retrato) e 1.91:1 (paisagem)
MAX_HEIGHT_RATIO = 1.25
REPO = "lucio-mw/mw-instagram-automatico"
TRIGGERS_FILE = ROOT / ".disparos.json"  # local, fora do git
MAX_TRIGGERS_PER_SLOT = 3  # se falhar 3 vezes, para de insistir e avisa


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def notify(msg):
    """Mostra uma notificação no macOS (para erros que precisam da sua atenção)."""
    log("AVISO: " + msg)
    script = 'display notification "{}" with title "Instagram automático"'.format(
        msg.replace('"', "'")
    )
    subprocess.run(["osascript", "-e", script], check=False)


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def is_ready(folder):
    newest = max((p.stat().st_mtime for p in folder.rglob("*")), default=folder.stat().st_mtime)
    return time.time() - newest > READY_AFTER_SECONDS


def validate_caption(caption):
    if not caption:
        return "legenda vazia"
    if len(caption) > MAX_CAPTION:
        return f"legenda com {len(caption)} caracteres (máx. {MAX_CAPTION})"
    hashtags = len(re.findall(r"#\w+", caption))
    if hashtags > MAX_HASHTAGS:
        return f"legenda com {hashtags} hashtags (máx. {MAX_HASHTAGS})"
    return None


def extract_carousel_caption(text):
    """O legenda.txt dos carrosséis tem várias seções (=== TOM ===, === SLIDES ===...).
    Só a seção === LEGENDA === vai para o Instagram."""
    match = re.search(r"^=== LEGENDA ===\s*$(.*?)(?=^=== .+ ===\s*$|\Z)", text, re.M | re.S)
    if match:
        return match.group(1).strip()
    return "" if re.search(r"^=== .+ ===\s*$", text, re.M) else text.strip()


def copy_image_4x5(src, dst):
    """Copia a imagem cortando o excesso de altura (centralizado) se passar de 4:5."""
    out = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(src)],
        check=True, capture_output=True, text=True,
    ).stdout
    width = int(re.search(r"pixelWidth: (\d+)", out).group(1))
    height = int(re.search(r"pixelHeight: (\d+)", out).group(1))
    max_height = int(width * MAX_HEIGHT_RATIO)
    if height > max_height:
        subprocess.run(
            ["sips", "-c", str(max_height), str(width), str(src), "--out", str(dst)],
            check=True, capture_output=True,
        )
    else:
        shutil.copy2(src, dst)


class Source:
    def __init__(self, queue, src_dir, name_pattern):
        self.queue = queue
        self.src_dir = src_dir
        self.name_pattern = re.compile(name_pattern)
        self.queue_dir = POSTS_DIR / queue
        self.published_dir = self.queue_dir / "publicados"

    def mark_published(self):
        """Marca no iCloud o que o GitHub já publicou. Devolve quantos foram marcados."""
        count = 0
        for marker in sorted(self.published_dir.glob("*.txt")):
            folder = self.src_dir / marker.stem
            if folder.is_dir():
                target = self.posted_path(marker.stem)
                if target.exists():
                    notify(f"{target.name} já existe; não movi {folder.name}")
                    continue
                folder.rename(target)
                log(f"{self.queue}: {folder.name} marcado como postado")
                count += 1
        return count

    def pending(self):
        if not self.src_dir.is_dir():
            notify(f"Pasta não encontrada: {self.src_dir}")
            return []
        found = []
        for folder in sorted(self.src_dir.iterdir()):
            name = folder.name
            if not folder.is_dir() or not self.name_pattern.match(name):
                continue
            if (self.queue_dir / name).exists() or (self.published_dir / f"{name}.txt").exists():
                continue
            found.append(folder)
        return found

    def enqueue(self, folder):
        """Copia um conteúdo do iCloud para a fila. Devolve True se copiou."""
        if not (folder / CAPTION_FILE).exists() or not is_ready(folder):
            return False
        caption = self.read_caption(folder)
        error = validate_caption(caption) or self.validate_media(folder)
        if error:
            notify(f"{folder.name}: {error}. Não vai ser postado até corrigir.")
            return False

        tmp = self.queue_dir / f".{folder.name}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        self.copy_media(folder, tmp)
        (tmp / CAPTION_FILE).write_text(caption + "\n", encoding="utf-8")
        dest = self.queue_dir / folder.name
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
        log(f"{self.queue}: {folder.name} adicionado à fila")
        return True


class Carousels(Source):
    def __init__(self):
        super().__init__("carrosseis", CAROUSELS_SRC, r"^\d{4}-\d{2}-\d{2}-")

    def posted_path(self, name):
        return self.src_dir / "Postados" / f"{POSTED_PREFIX}{name}"

    def images(self, folder):
        return sorted(p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg"))

    def read_caption(self, folder):
        return extract_carousel_caption((folder / CAPTION_FILE).read_text(encoding="utf-8"))

    def validate_media(self, folder):
        n = len(self.images(folder))
        if n == 0:
            return "nenhuma imagem .jpg"
        if n > MAX_CAROUSEL:
            return f"{n} imagens (máx. {MAX_CAROUSEL} por carrossel)"
        return None

    def copy_media(self, folder, dst):
        for image in self.images(folder):
            copy_image_4x5(image, dst / image.name)


class Reels(Source):
    VIDEO = "imagem_reel.mp4"

    def __init__(self):
        super().__init__("reels", REELS_SRC, r"^\d+-")

    def posted_path(self, name):
        return self.src_dir / f"{POSTED_PREFIX}{name}"

    def read_caption(self, folder):
        return (folder / CAPTION_FILE).read_text(encoding="utf-8").strip()

    def validate_media(self, folder):
        return None if (folder / self.VIDEO).exists() else f"falta o {self.VIDEO}"

    def tracks(self):
        if not AUDIO_SRC.is_dir():
            return []
        return sorted(p for p in AUDIO_SRC.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS)

    def pending(self):
        found = super().pending()
        # Reels que entraram na fila sem áudio são refeitos quando houver trilhas
        if self.tracks() and self.queue_dir.is_dir():
            for queued in sorted(self.queue_dir.iterdir()):
                source = self.src_dir / queued.name
                if (queued.is_dir() and queued.name != "publicados"
                        and not (queued / AUDIO_MARKER).exists() and source.is_dir()):
                    found.append(source)
        return found

    def copy_media(self, folder, dst):
        video = folder / self.VIDEO
        tracks = self.tracks()
        if not tracks:
            shutil.copy2(video, dst / "video.mp4")
            return
        number = re.match(r"\d+", folder.name)
        track = tracks[(int(number.group()) - 1 if number else 0) % len(tracks)]
        duration = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video)],
            check=True, capture_output=True, text=True,
        ).stdout)
        fade = min(1.5, duration / 4)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-i", str(video), "-stream_loop", "-1", "-i", str(track),
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
             "-af", f"afade=t=in:d=0.3,afade=t=out:st={duration - fade:.2f}:d={fade:.2f},"
                    "loudnorm=I=-16:TP=-1.5",
             "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
             "-t", f"{duration:.2f}", "-movflags", "+faststart", str(dst / "video.mp4")],
            check=True, capture_output=True,
        )
        (dst / AUDIO_MARKER).write_text(track.name + "\n", encoding="utf-8")


def gh(*args):
    return subprocess.run(
        ["gh", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def trigger_if_due():
    """Dispara a publicação no GitHub se um horário da agenda venceu sem post."""
    from post_instagram import due_slot

    due = due_slot()
    if due is None:
        return
    queue, slot = due
    running = gh("run", "list", "-R", REPO, "--workflow", "instagram.yml",
                 "--json", "status", "-q", '[.[] | select(.status != "completed")] | length')
    if running != "0":
        log(f"Horário {slot} vencido, mas já há uma publicação em andamento.")
        return
    try:
        triggers = json.loads(TRIGGERS_FILE.read_text())
    except (OSError, ValueError):
        triggers = {}
    count = triggers.get(slot, 0)
    if count >= MAX_TRIGGERS_PER_SLOT:
        if count == MAX_TRIGGERS_PER_SLOT:
            notify(f"A publicação de {slot} falhou {count} vezes. Veja a aba Actions no GitHub.")
            triggers[slot] = count + 1
            TRIGGERS_FILE.write_text(json.dumps(triggers))
        return
    gh("workflow", "run", "instagram.yml", "-R", REPO, "-f", "fila=auto")
    triggers = {k: v for k, v in triggers.items() if k[:10] == slot[:10]}  # só guarda hoje
    triggers[slot] = count + 1
    TRIGGERS_FILE.write_text(json.dumps(triggers))
    log(f"Horário {slot} ({queue}) vencido: publicação disparada no GitHub.")


def main():
    # logo depois de acordar a rede pode demorar alguns segundos para voltar
    for attempt in range(6):
        try:
            git("pull", "--rebase", "--autostash", "-q")
            break
        except subprocess.CalledProcessError as e:
            if attempt == 5:
                notify("Não consegui baixar do GitHub (git pull). Veja o log.")
                log(e.stderr)
                sys.exit(1)
            time.sleep(10)

    sync_queue()
    try:
        trigger_if_due()
    except subprocess.CalledProcessError as e:
        notify("Não consegui disparar a publicação no GitHub. Veja o log.")
        log(e.stderr)


def sync_queue():
    changed = False
    for source in (Carousels(), Reels()):
        source.mark_published()
        for folder in source.pending():
            changed |= source.enqueue(folder)

    if not changed:
        log("Nada novo.")
        return

    git("add", "-A", "posts")
    if not git("status", "--porcelain", "posts"):
        return
    git("commit", "-q", "-m", f"Fila atualizada pelo Mac em {datetime.now():%Y-%m-%d %H:%M}")
    try:
        git("push", "-q")
    except subprocess.CalledProcessError as e:
        notify("Não consegui enviar a fila ao GitHub (git push). Veja o log.")
        log(e.stderr)
        sys.exit(1)
    log("Fila enviada ao GitHub.")


if __name__ == "__main__":
    main()
