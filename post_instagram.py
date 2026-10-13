#!/usr/bin/env python3
"""Publica no Instagram o próximo post de uma fila.

Uso:  python post_instagram.py carrosseis
      python post_instagram.py reels

Cada fila é uma pasta em posts/ com uma subpasta por post, já preparada pelo
sync_icloud.py:

  posts/carrosseis/<nome>/slide-01.jpg ... slide-NN.jpg + legenda.txt
  posts/reels/<nome>/video.mp4 + legenda.txt

Os posts saem em ordem (número/data do começo do nome). Depois de publicado, a
subpasta é apagada e fica só um registro em posts/<fila>/publicados/<nome>.txt,
que o sync_icloud.py usa para marcar a pasta original no iCloud como postada.

Carrosséis: a API exige que cada imagem esteja numa URL pública. Se
IMGBB_API_KEY estiver definida, a imagem vai para o ImgBB por 24h (necessário
com repositório privado); senão usa IMAGE_BASE_URL ou o raw.githubusercontent.com
do repositório (precisa ser público).
Reels: o vídeo é enviado direto para o Instagram (upload resumível), sem
hospedagem externa.

Variáveis de ambiente:
  IG_USER_ID        ID da conta profissional do Instagram (obrigatória)
  IG_ACCESS_TOKEN   token de acesso de longa duração (obrigatória)
  IG_API_HOST       graph.facebook.com (padrão) ou graph.instagram.com
  IG_API_VERSION    padrão v23.0
  IMGBB_API_KEY     ver acima
  IMAGE_BASE_URL    ver acima
  DRY_RUN=1         mostra o que seria publicado sem publicar nada

Só usa a biblioteca padrão do Python (sem dependências).
"""

import base64
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "posts"
CAPTION_FILE = "legenda.txt"
VIDEO_FILE = "video.mp4"
IMAGE_EXTENSIONS = {".jpg", ".jpeg"}  # a API do Instagram só aceita JPEG
MAX_CAROUSEL = 10
QUEUES = ("carrosseis", "reels")


def env(name, default=None, required=False):
    value = os.environ.get(name, "").strip() or default
    if required and not value:
        sys.exit(f"Erro: defina a variável de ambiente {name}.")
    return value


def request(url, data=None, raw=None, headers=None):
    """GET (sem data), POST form-encoded (data) ou POST binário (raw). Devolve o JSON."""
    body = urllib.parse.urlencode(data).encode() if data is not None else raw
    req = urllib.request.Request(url, data=body, headers=headers or {})
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


def public_url(image):
    imgbb_key = env("IMGBB_API_KEY")
    if imgbb_key:
        result = request(
            "https://api.imgbb.com/1/upload?expiration=86400&key=" + imgbb_key,
            {"image": base64.b64encode(image.read_bytes()).decode()},
        )
        return result["data"]["url"]

    rel_path = image.relative_to(ROOT).as_posix()
    base = env("IMAGE_BASE_URL")
    if not base:
        repo = env("GITHUB_REPOSITORY")
        branch = env("GITHUB_REF_NAME", "main")
        if not repo:
            sys.exit("Erro: defina IMGBB_API_KEY ou IMAGE_BASE_URL para rodar fora do GitHub Actions.")
        base = f"https://raw.githubusercontent.com/{repo}/{branch}"
    return f"{base.rstrip('/')}/{urllib.parse.quote(rel_path)}"


class Instagram:
    def __init__(self):
        host = env("IG_API_HOST", "graph.facebook.com")
        self.version = env("IG_API_VERSION", "v23.0")
        self.user_id = env("IG_USER_ID", required=True)
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
        created = self.create_container(
            media_type="REELS", upload_type="resumable", caption=caption, share_to_feed="true"
        )
        container = created["id"]
        upload_uri = created.get("uri") or (
            f"https://rupload.facebook.com/ig-api-upload/{self.version}/{container}"
        )
        data = video.read_bytes()
        request(
            upload_uri,
            raw=data,
            headers={
                "Authorization": f"OAuth {self.token}",
                "offset": "0",
                "file_size": str(len(data)),
            },
        )
        print(f"  vídeo enviado ({len(data) // 1024} KB), aguardando processamento...")
        self.wait_ready(container)
        return self.publish(container)


def archive(queue_dir, folder, media_id):
    published = queue_dir / "publicados"
    published.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    (published / f"{folder.name}.txt").write_text(
        f"publicado_em: {now}\nmedia_id: {media_id}\n", encoding="utf-8"
    )
    shutil.rmtree(folder)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in QUEUES:
        sys.exit(f"Uso: python {Path(__file__).name} {'|'.join(QUEUES)}")
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

    if env("DRY_RUN") == "1":
        print("DRY_RUN=1: nada foi publicado.")
        return

    ig = Instagram()
    media_id = ig.post_reel(media, caption) if queue == "reels" else ig.post_carousel(media, caption)
    print(f"Publicado com sucesso! ID da mídia: {media_id}")
    archive(queue_dir, folder, media_id)


if __name__ == "__main__":
    main()
