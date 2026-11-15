// Cloudflare Worker que lanza la actualización de noticias cada 15 minutos.
// GitHub a veces retrasa o se salta sus horarios; los de Cloudflare son puntuales.
// Necesita:
//   - un secreto GITHUB_TOKEN: token fine-grained con "Actions: Read and write" en noticias-espana
//   - un Cron Trigger: "*/15 * * * *"

const REPO = "alexample/noticias-espana";
const WORKFLOW = "publicar.yml";

async function launch(env) {
  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "User-Agent": "noticias-espana-cron",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  const text = res.status === 204 ? "" : await res.text();
  console.log(`GitHub respondió ${res.status} ${text}`);
  if (res.status !== 204) throw new Error(`No se pudo lanzar la actualización: ${res.status} ${text}`);
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(launch(env));
  },
  async fetch() {
    return new Response("Noticias España: cron activo. La actualización se lanza sola cada 15 minutos.", {
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  },
};
