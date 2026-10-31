#!/usr/bin/env python3
"""Coleta as métricas orgânicas dos posts do @mwcapital.inc.

Roda no GitHub Actions (workflow metricas.yml) com o mesmo token do post_instagram.py.
Grava metricas.json; o workflow cifra o arquivo com metricas_chave_publica.pem antes de
subir como artefato, porque os logs e artefatos deste repositório são públicos.
O log só mostra contagens, nunca números de posts.

Variáveis: IG_ACCESS_TOKEN (obrigatória), IG_USER_ID, IG_API_HOST, IG_API_VERSION.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST = os.environ.get("IG_API_HOST") or "graph.instagram.com"
VERSION = os.environ.get("IG_API_VERSION") or "v23.0"
USER = os.environ.get("IG_USER_ID") or "me"
TOKEN = os.environ.get("IG_ACCESS_TOKEN") or sys.exit("Erro: IG_ACCESS_TOKEN ausente.")
API = f"https://{HOST}/{VERSION}"

# métricas por tipo; se alguma não existir, tenta de novo com o conjunto mínimo
METRICAS = {
    "REELS": "views,reach,saved,shares,total_interactions,ig_reels_avg_watch_time",
    "FEED": "views,reach,saved,shares,total_interactions",
}
MINIMO = "reach,saved"


def get(path, **params):
    params["access_token"] = TOKEN
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error", {})
        except Exception:
            err = {}
        return None, f"HTTP {e.code} code={err.get('code')} sub={err.get('error_subcode')}: {err.get('message', '')[:160]}"


def main():
    posts, after = [], None
    while True:
        params = {"fields": "id,caption,media_type,media_product_type,timestamp,permalink", "limit": 100}
        if after:
            params["after"] = after
        data, err = get(f"{USER}/media", **params)
        if err:
            sys.exit(f"Erro ao listar posts: {err}")
        posts += data.get("data", [])
        after = data.get("paging", {}).get("cursors", {}).get("after")
        if not data.get("paging", {}).get("next"):
            break

    erros = {}
    for p in posts:
        tipo = p.get("media_product_type", "FEED")
        dados, err = get(f"{p['id']}/insights", metric=METRICAS.get(tipo, METRICAS["FEED"]))
        if err:
            dados, err2 = get(f"{p['id']}/insights", metric=MINIMO)
            if err2:
                erros[err2] = erros.get(err2, 0) + 1
                continue
        p["insights"] = {m["name"]: (m.get("values") or [{}])[0].get("value") for m in dados["data"]}

    with open("metricas.json", "w") as f:
        json.dump(posts, f, ensure_ascii=False, indent=1)
    com = sum(1 for p in posts if "insights" in p)
    print(f"{len(posts)} posts listados, {com} com métricas.")
    for e, n in erros.items():
        print(f"  {n}x {e}")


if __name__ == "__main__":
    main()
