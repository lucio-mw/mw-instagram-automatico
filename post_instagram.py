#!/usr/bin/env python3
"""Publica no Instagram o próximo post de uma fila.

Uso:  python post_instagram.py auto         publica o que estiver vencido na agenda
      python post_instagram.py reels        publica o próximo reel agora (extra)
      python post_instagram.py carrosseis   publica o próximo carrossel agora (extra)

O agendador do GitHub atrasa e às vezes pula execuções, então o modo "auto"
roda a cada 15 minutos e confere a AGENDA: se um horário de hoje já passou (há
menos de JANELA_HORAS) e ainda não tem post registrado, publica agora.

Cada fila é uma pasta em posts/ com uma subpasta por post, já preparada pelo
sync_icloud.py:

  posts/carrosseis/<nome>/slide-01.jpg ... slide-NN.jpg + legenda.txt
  posts/reels/<nome>/video.mp4 + legenda.txt

Os posts saem em ordem (número/data do começo do nome). Depois de publicado, a
subpasta é apagada e fica só um registro em posts/<fila>/publicados/<nome>.txt,
que o sync_icloud.py usa para marcar a pasta original no iCloud como postada.

A API exige que cada imagem e vídeo esteja numa URL pública: o Instagram baixa
os arquivos direto do raw.githubusercontent.com deste repositório (que por isso
é público), ou de MEDIA_BASE_URL se definida.

Variáveis de ambiente:
  IG_USER_ID        ID da conta do Instagram (padrão "me" = dona do token)
  IG_ACCESS_TOKEN   token de acesso de longa duração (obrigatória)
  IG_API_HOST       graph.instagram.com (padrão, Login do Instagram) ou graph.facebook.com
  IG_API_VERSION    padrão v23.0
  MEDIA_BASE_URL    opcional, ver acima
  DRY_RUN=1         mostra o que seria publicado sem publicar nada

Só usa a biblioteca padrão do Python (sem dependências).
"""

import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "posts"
CAPTION_FILE = "legenda.txt"
VIDEO_FILE = "video.mp4"
IMAGE_EXTENSIONS = {".jpg", ".jpeg"}  # a API do Instagram só aceita JPEG
MAX_CAROUSEL = 10
QUEUES = ("carrosseis", "reels")
TIMEZONE = ZoneInfo("America/Sao_Paulo")
AGENDA = [("09:00", "reels"), ("12:00", "carrosseis"), ("19:00", "reels")]
JANELA_HORAS = 6  # depois disso um horário perdido é descartado


def env(name, default=None, required=False):
    value = os.environ.get(name, "").strip() or default
    if required and not value:
        sys.exit(f"Erro: defina a variável de ambiente {name}.")
    return value


def request(url, data=None):
    """Faz GET (data=None) ou POST form-encoded e devolve o JSON da resposta."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        sys.exit(f"Erro HTTP {e.code} em {url.split('?')[0]}:\n{detail}")


def sort_key(path):
    """Ordena pelo número do começo do nome (01, 02... 100) e depois pelo nome."""
    match = re.match(r"\d+", path.name)
    return (int(match.group()) if match else float("inf"), path.name)


def images_in(folder):
    return sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def next_post(queue_dir):
    if not queue_dir.exists():
        return None
    folders = [p for p in queue_dir.iterdir() if p.is_dir() and p.name != "publicados"]
    return min(folders, key=sort_key) if folders else None


def public_url(path):
    rel_path = urllib.parse.quote(path.relative_to(ROOT).as_posix())
    base = env("MEDIA_BASE_URL")
    if not base:
        repo = env("GITHUB_REPOSITORY")
        if not repo:
            sys.exit("Erro: defina MEDIA_BASE_URL para rodar fora do GitHub Actions.")
        # o commit exato evita cache de versões antigas no raw.githubusercontent.com
        base = f"https://raw.githubusercontent.com/{repo}/{env('GITHUB_SHA', 'main')}"
    return f"{base.rstrip('/')}/{rel_path}"


class Instagram:
    def __init__(self):
        host = env("IG_API_HOST", "graph.instagram.com")
        self.version = env("IG_API_VERSION", "v23.0")
        self.user_id = env("IG_USER_ID", "me")
        self.token = env("IG_ACCESS_TOKEN", required=True)
        self.api = f"https://{host}/{self.version}"

    def create_container(self, **params):
        return request(f"{self.api}/{self.user_id}/media", dict(params, access_token=self.token))

    def wait_ready(self, container, attempts=60, interval=10):
        for _ in range(attempts):
            status = request(
                f"{self.api}/{container}?fields=status_code"
                f"&access_token={urllib.parse.quote(self.token)}"
            ).get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                sys.exit(f"Erro: o Instagram não conseguiu processar a mídia (status {status}).")
            time.sleep(interval)
        sys.exit("Erro: tempo esgotado esperando o Instagram processar a mídia.")

    def publish(self, container):
        return request(
            f"{self.api}/{self.user_id}/media_publish",
            {"creation_id": container, "access_token": self.token},
        )["id"]

    def post_carousel(self, images, caption):
        if len(images) == 1:
            container = self.create_container(image_url=public_url(images[0]), caption=caption)["id"]
        else:
            children = []
            for i, image in enumerate(images, 1):
                children.append(
                    self.create_container(image_url=public_url(image), is_carousel_item="true")["id"]
                )
                print(f"  slide {i}/{len(images)} enviado")
            for child in children:
                self.wait_ready(child, interval=3)
            container = self.create_container(
                media_type="CAROUSEL", children=",".join(children), caption=caption
            )["id"]
        self.wait_ready(container, interval=3)
        return self.publish(container)

    def post_reel(self, video, caption):
        container = self.create_container(
            media_type="REELS", video_url=public_url(video), caption=caption, share_to_feed="true"
        )["id"]
        print("  vídeo enviado, aguardando processamento...")
        self.wait_ready(container)
        return self.publish(container)


def archive(queue_dir, folder, media_id, slot=None):
    published = queue_dir / "publicados"
    published.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    record = f"publicado_em: {now}\nmedia_id: {media_id}\n"
    if slot:
        record += f"horario: {slot}\n"
    (published / f"{folder.name}.txt").write_text(record, encoding="utf-8")
    shutil.rmtree(folder)


def due_slot():
    """Devolve (fila, horário) do primeiro horário vencido de hoje sem post, ou None."""
    now = datetime.now(TIMEZONE)
    filled = set()
    for record in POSTS_DIR.glob("*/publicados/*.txt"):
        for line in record.read_text(encoding="utf-8").splitlines():
            if line.startswith("horario: "):
                filled.add(line[len("horario: "):].strip())
    for hhmm, queue in AGENDA:
        hour, minute = map(int, hhmm.split(":"))
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        slot = when.strftime("%Y-%m-%d %H:%M")
        if when <= now < when + timedelta(hours=JANELA_HORAS) and slot not in filled:
            if next_post(POSTS_DIR / queue) is not None:
                return queue, slot
    return None


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in QUEUES + ("auto",):
        sys.exit(f"Uso: python {Path(__file__).name} auto|{'|'.join(QUEUES)}")
    slot = None
    if sys.argv[1] == "auto":
        due = due_slot()
        if due is None:
            print("Nenhum horário vencido com post na fila. Nada a publicar.")
            return
        queue, slot = due
        print(f"Horário {slot} ({queue}) vencido e ainda sem post.")
    else:
        queue = sys.argv[1]
    queue_dir = POSTS_DIR / queue
    folder = next_post(queue_dir)
    if folder is None:
        print(f"Fila '{queue}' vazia. Nada a publicar.")
        return

    caption_path = folder / CAPTION_FILE
    caption = caption_path.read_text(encoding="utf-8").strip() if caption_path.exists() else ""

    if queue == "reels":
        media = folder / VIDEO_FILE
        if not media.exists():
            sys.exit(f"Erro: {folder.name} não tem {VIDEO_FILE}.")
        print(f"Próximo reel: {folder.name}")
    else:
        media = images_in(folder)
        if not media:
            sys.exit(f"Erro: {folder.name} não tem imagens .jpg.")
        if len(media) > MAX_CAROUSEL:
            sys.exit(f"Erro: o carrossel tem {len(media)} imagens; o limite da API é {MAX_CAROUSEL}.")
        print(f"Próximo carrossel: {folder.name} ({len(media)} imagens)")
    print(f"Legenda:\n{caption or '(sem legenda)'}\n")

    ig = Instagram()

    if env("DRY_RUN") == "1":
        account = request(
            f"{ig.api}/{ig.user_id}?fields=username"
            f"&access_token={urllib.parse.quote(ig.token)}"
        )
        print(f"Conexão OK com a conta @{account.get('username')}.")
        print("DRY_RUN=1: nada foi publicado.")
        return

    media_id = ig.post_reel(media, caption) if queue == "reels" else ig.post_carousel(media, caption)
    print(f"Publicado com sucesso! ID da mídia: {media_id}")
    archive(queue_dir, folder, media_id, slot)


if __name__ == "__main__":
    main()
