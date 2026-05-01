"""Plantilla content_seo — site Astro estático con N artículos generados.

LLM calls:
1. Cluster de 5 títulos con intent + keyword principal.
2-6. Cada artículo (markdown 800-1200 palabras con frontmatter Astro).

Build multi-stage Node→nginx. Healthcheck timeout 180s (Astro build lento).
"""
import json
import re
import sys
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.llm import ask_json, ask_text


CLUSTER_SYSTEM = """Eres un SEO strategist. Recibes un pain point y
generas un cluster de 5 títulos de artículos que capturan distintas
queries del nicho.

Reglas:
- Cada título debe ser un H1 que capture una query real (cómo, qué, por qué, mejor X).
- Mix de intents: 2 informational, 2 commercial/comparativo, 1 navigational/branded.
- Sin años en el título.
- Idioma: inglés (la mayoría de fuentes de scout son EN).

Devuelve SOLO JSON:
{
  "cluster_topic": "frase corta del tema central",
  "articles": [
    {"slug": "kebab-case", "title": "...", "intent": "informational|commercial|navigational", "keyword": "..."},
    ... 5 entries
  ]
}
"""


ARTICLE_SYSTEM = """Generas un artículo SEO de blog en formato Markdown.

Reglas:
- 800-1200 palabras.
- Frontmatter Astro:
  ---
  title: "..."
  description: "..."  (155-160 chars, meta description optimizada)
  pubDate: 2026-04-30
  ---
- 3-5 H2 con su contenido. Algún H3 si lo merece.
- Tono: directo, sin fluff, sin emojis. Como un IndieHacker que sabe del tema.
- Incluir 1-2 ejemplos concretos numéricos.
- NO inventar marcas/productos específicos como si existieran.

Devuelve SOLO el markdown, sin code fence."""


def slugify(s: str, maxlen: int = 50) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:maxlen] or "post"


def build(opp: dict, dest_dir: Path, port: int | None = None) -> dict:
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "src" / "content" / "posts").mkdir(parents=True, exist_ok=True)
    (dest_dir / "src" / "pages").mkdir(parents=True, exist_ok=True)

    # 1. Cluster
    cluster_user = (
        f"## Pain point\n{opp['pain_point']}\n\n"
        f"## Título original\n{opp['title']}\n\n"
        f"Genera el cluster de 5 artículos."
    )
    cluster = ask_json(CLUSTER_SYSTEM, cluster_user, max_tokens=2000)

    # 2-6. Artículos
    articles = cluster.get("articles", [])[:5]
    written: list[dict] = []
    for i, art in enumerate(articles):
        article_user = (
            f"Título: {art['title']}\n"
            f"Intent: {art['intent']}\n"
            f"Keyword: {art['keyword']}\n"
            f"Cluster topic: {cluster.get('cluster_topic', '')}\n\n"
            f"Genera el artículo completo."
        )
        body = ask_text(ARTICLE_SYSTEM, article_user, max_tokens=3500)
        if body.startswith("```"):
            lines = body.splitlines()
            body = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        slug = slugify(art["slug"])
        (dest_dir / "src" / "content" / "posts" / f"{slug}.md").write_text(body)
        written.append({"slug": slug, "title": art["title"], "keyword": art["keyword"]})

    # Astro config + package.json
    (dest_dir / "package.json").write_text(json.dumps({
        "name": dest_dir.name,
        "type": "module",
        "version": "0.1.0",
        "scripts": {
            "build": "astro build",
            "dev": "astro dev"
        },
        "dependencies": {
            "astro": "^4.16.0"
        }
    }, indent=2))

    (dest_dir / "astro.config.mjs").write_text(dedent("""\
        import { defineConfig } from 'astro/config';
        export default defineConfig({
          site: 'http://localhost',
          build: { format: 'directory' }
        });
    """))

    # Content collection schema
    (dest_dir / "src" / "content" / "config.ts").write_text(dedent("""\
        import { defineCollection, z } from 'astro:content';
        const posts = defineCollection({
          type: 'content',
          schema: z.object({
            title: z.string(),
            description: z.string().optional(),
            pubDate: z.coerce.date(),
          }),
        });
        export const collections = { posts };
    """))

    # Index page lista los posts
    index_astro = dedent("""\
        ---
        import { getCollection } from 'astro:content';
        const posts = (await getCollection('posts')).sort(
          (a, b) => b.data.pubDate.valueOf() - a.data.pubDate.valueOf()
        );
        ---
        <html lang="en">
          <head>
            <meta charset="utf-8" />
            <title>Articles</title>
            <meta name="viewport" content="width=device-width" />
            <style>
              body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; color: #111; line-height: 1.6; }
              a { color: #2563eb; text-decoration: none; }
              a:hover { text-decoration: underline; }
              ul { list-style: none; padding: 0; }
              li { margin: 1rem 0; padding-bottom: 1rem; border-bottom: 1px solid #eee; }
              h2 { margin: 0; font-size: 1.2rem; }
              p { color: #555; margin: 0.3rem 0 0 0; }
            </style>
          </head>
          <body>
            <h1>Articles</h1>
            <ul>
              {posts.map((p) => (
                <li>
                  <h2><a href={`/posts/${p.slug}/`}>{p.data.title}</a></h2>
                  {p.data.description && <p>{p.data.description}</p>}
                </li>
              ))}
            </ul>
          </body>
        </html>
    """)
    (dest_dir / "src" / "pages" / "index.astro").write_text(index_astro)

    # Página por post: src/pages/posts/[...slug].astro
    posts_dir = dest_dir / "src" / "pages" / "posts"
    posts_dir.mkdir(exist_ok=True)
    (posts_dir / "[...slug].astro").write_text(dedent("""\
        ---
        import { getCollection } from 'astro:content';
        export async function getStaticPaths() {
          const posts = await getCollection('posts');
          return posts.map(p => ({ params: { slug: p.slug }, props: { post: p } }));
        }
        const { post } = Astro.props;
        const { Content } = await post.render();
        ---
        <html lang="en">
          <head>
            <meta charset="utf-8" />
            <title>{post.data.title}</title>
            <meta name="description" content={post.data.description || ''} />
            <meta name="viewport" content="width=device-width" />
            <style>
              body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; color: #111; line-height: 1.7; }
              a { color: #2563eb; }
              h1 { font-size: 2rem; }
              h2 { margin-top: 2rem; }
              code { background: #f3f4f6; padding: 0.1rem 0.3rem; border-radius: 3px; }
              pre { background: #f3f4f6; padding: 1rem; overflow-x: auto; }
            </style>
          </head>
          <body>
            <a href="/">← Back</a>
            <article>
              <h1>{post.data.title}</h1>
              <Content />
            </article>
          </body>
        </html>
    """))

    # Dockerfile multi-stage
    (dest_dir / "Dockerfile").write_text(dedent("""\
        FROM node:22-alpine AS build
        WORKDIR /app
        COPY package*.json ./
        RUN npm install
        COPY . .
        RUN npm run build

        FROM nginx:alpine
        COPY --from=build /app/dist /usr/share/nginx/html
        EXPOSE 80
    """))

    # Port hardcoded (mismo motivo que microsaas).
    host_port = port or 8080
    (dest_dir / "docker-compose.yml").write_text(dedent(f"""\
        services:
          web:
            build: .
            container_name: biz-hunter-project-{dest_dir.name}
            ports:
              - "{host_port}:80"
            restart: unless-stopped
    """))

    spec_md = dedent(f"""\
        # {opp['title']}

        ## Cluster: {cluster.get('cluster_topic', '?')}

        ## Pain point original
        {opp['pain_point']}

        ## Artículos generados ({len(written)})
    """) + "\n".join(f"- `{w['slug']}` — {w['title']} (kw: `{w['keyword']}`)" for w in written)

    (dest_dir / "PROJECT_SPEC.md").write_text(spec_md)

    (dest_dir / "README.md").write_text(dedent(f"""\
        # {dest_dir.name}

        Astro static site con {len(written)} artículos seed sobre el cluster
        "{cluster.get('cluster_topic', '?')}".

        ## Run
        ```bash
        docker compose up -d --build
        # http://localhost:{host_port}
        ```

        ## Itera
        - Posts: `src/content/posts/*.md`
        - Layout: `src/pages/index.astro` y `src/pages/posts/[...slug].astro`
        - Spec: `PROJECT_SPEC.md`
    """))

    return {
        "framework": "astro",
        "has_docker": True,
        "healthcheck_timeout_s": 240,  # Astro build + nginx start
        "spec_md": spec_md,
    }
