# Instagram automático — MW Capital

Publica automaticamente no **@mwcapital.inc**, usando a API oficial da Meta
(Login do Instagram) e o GitHub Actions — funciona com o Mac desligado.

| Horário (Brasília) | O quê |
|--------------------|-------|
| 09:00 | Reel da *Postagem Diaria Instagram* |
| 12:00 | Carrossel novo da *Carrosseis Claude* (se houver) |
| 19:00 | Reel da *Postagem Diaria Instagram* |

## Como funciona

```
iCloud (Documentos MW Capital/Instagram)
  ├─ Carrosseis Claude/2026-..-..-tema/   slides .jpg + legenda.txt
  └─ Postagem Diaria Instagram/NN-tema/   imagem_reel.mp4 + legenda.txt
        │
        │  sync_icloud.py — no Mac, a cada 15 min (app "MW Instagram Sync")
        ▼
GitHub: lucio-mw/mw-instagram-automatico (privado)
  posts/carrosseis/<nome>/  slides cortados em 4:5 + só a seção === LEGENDA ===
  posts/reels/<nome>/       video.mp4 + legenda.txt
        │
        │  post_instagram.py — GitHub Actions nos horários acima
        ▼
Instagram  →  registra em posts/<fila>/publicados/<nome>.txt
        │
        │  sync_icloud.py marca no iCloud:
        ▼
  carrossel → movido para Carrosseis Claude/Postados/Postado-<nome>
  reel      → renomeado para Postagem Diaria Instagram/Postado-<nome>
```

- Para entrar na fila, um conteúdo precisa ter `legenda.txt`, a mídia, e ficar
  5 minutos sem alteração (para não pegar um carrossel ainda sendo gerado).
- Os posts saem em ordem: data (carrosséis) ou número (reels).
- Se uma legenda passar de 2.200 caracteres ou 30 hashtags, ou um carrossel tiver
  mais de 10 slides, o Mac mostra uma notificação e o post não entra na fila.
- **Para não postar algo que já está na fila:** apague a pasta em `posts/` no GitHub.
- O Mac só precisa estar ligado em algum momento antes do horário do post.

## Secrets do GitHub

Em *Settings → Secrets and variables → Actions* do repositório:

| Secret | Valor |
|--------|-------|
| `IG_ACCESS_TOKEN` | Token gerado no app da Meta (*Configuração da API com login do Instagram*) |
| `IMGBB_API_KEY` | Chave de [api.imgbb.com](https://api.imgbb.com) (hospeda as imagens dos carrosséis por 24h) |

> ⚠️ O token do Instagram expira em **60 dias**. Gere outro no painel da Meta e
> atualize o secret: `gh secret set IG_ACCESS_TOKEN -R lucio-mw/mw-instagram-automatico`

## Comandos úteis

```bash
# Publicar/simular manualmente (ou pela aba Actions → Run workflow)
gh workflow run instagram.yml -R lucio-mw/mw-instagram-automatico -f fila=reels -f dry_run=true

# Ver as últimas execuções
gh run list -R lucio-mw/mw-instagram-automatico

# Log da sincronização do Mac
tail -f ~/Library/Logs/mw-instagram-sync.log

# Reinstalar / remover a sincronização do Mac
./instalar_mac.sh
./instalar_mac.sh --remover
```

## Mudar horários

Edite os `cron` em `.github/workflows/instagram.yml` (horário em UTC; Brasília = UTC−3).
Se mudar o horário do carrossel, mude também o `'0 15 * * *'` na linha `FILA:`.
