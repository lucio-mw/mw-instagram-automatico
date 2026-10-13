# Post diário no Instagram

Publica automaticamente **um post por dia** no Instagram, usando a API oficial da Meta
e rodando de graça no GitHub Actions (funciona com o computador desligado).

## Como funciona

1. Você coloca as imagens na pasta `posts/`, com a legenda num `.txt` de mesmo nome:
   ```
   posts/
     001.jpg   001.txt
     002.jpg   002.txt
   ```
2. Todo dia às 12:00 (Brasília), o GitHub Actions roda `post_instagram.py`, que publica
   a **primeira imagem em ordem alfabética**.
3. Depois de publicado, o par imagem + legenda vai para `posts/publicados/`.
   Se a fila estiver vazia, nada acontece.

Regras do Instagram: imagens **JPEG** (`.jpg`), proporção entre 4:5 e 1.91:1, até 8 MB.
Legenda até 2.200 caracteres e 30 hashtags. Limite de 50 posts por dia via API.

## Configuração (uma vez só)

### 1. Conta do Instagram

- A conta precisa ser **Profissional** (Business ou Criador de conteúdo).
- Crie um app em [developers.facebook.com](https://developers.facebook.com/apps) e adicione
  o produto **Instagram**. Há dois caminhos:
  - **Login do Instagram** (mais simples, não precisa de Página do Facebook): permissões
    `instagram_business_basic` e `instagram_business_content_publish`. Nesse caso defina a
    variável `IG_API_HOST` = `graph.instagram.com` (passo 3).
  - **Login do Facebook**: a conta do Instagram precisa estar ligada a uma Página do Facebook.
    Permissões `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
    `pages_read_engagement`.
- Gere um **token de longa duração** e anote o **ID da conta do Instagram** (`IG_USER_ID`).

> ⚠️ Tokens de longa duração expiram em **60 dias**. Renove antes disso e atualize o
> secret, ou (no caminho do Facebook) use um token de *System User* do Business Manager,
> que não expira.

### 2. Repositório no GitHub

Suba esta pasta para um repositório novo no GitHub.

- **Repositório público:** funciona direto — o Instagram baixa a imagem pelo
  `raw.githubusercontent.com`.
- **Repositório privado:** o Instagram não consegue acessar a imagem. Crie uma conta
  grátis no [ImgBB](https://api.imgbb.com/), pegue a API key e cadastre o secret
  `IMGBB_API_KEY`. O script envia a imagem para lá temporariamente (apagada em 24h).

### 3. Secrets e variáveis

No repositório: **Settings → Secrets and variables → Actions**.

| Tipo     | Nome              | Valor                                              |
|----------|-------------------|----------------------------------------------------|
| Secret   | `IG_USER_ID`      | ID da conta do Instagram                           |
| Secret   | `IG_ACCESS_TOKEN` | Token de longa duração                             |
| Secret   | `IMGBB_API_KEY`   | Só se o repositório for privado                    |
| Variable | `IG_API_HOST`     | `graph.instagram.com` se usar o Login do Instagram |

### 4. Testar

Na aba **Actions → Post diário no Instagram → Run workflow**:
- marque **"Só simular"** para ver qual post seria publicado sem publicar;
- desmarque para publicar de verdade agora.

## Mudar o horário

Edite a linha `cron` em `.github/workflows/instagram-diario.yml` (horário em UTC;
Brasília = UTC−3). Ex.: `"0 21 * * *"` = 18:00 em Brasília. O GitHub pode atrasar
execuções agendadas em alguns minutos.

## Rodar no seu computador

```bash
IG_USER_ID=... IG_ACCESS_TOKEN=... IMGBB_API_KEY=... python3 post_instagram.py
```

Use `DRY_RUN=1` para só simular.
