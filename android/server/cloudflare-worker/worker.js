/**
 * Guardian heartbeat — Cloudflare Worker edition (free, always-on, no hardware).
 *
 * The phone POSTs to /beat every ~15 min. A Cron Trigger runs scheduled() every 5 min and,
 * if a device has gone silent past GRACE_MINUTES, emails you via Resend (free tier). Cron
 * Triggers fire even with zero traffic, so this catches a full uninstall / power-off / force-stop.
 *
 * State lives in Workers KV. Email goes through Resend's HTTP API (Workers can't do raw SMTP).
 *
 * Setup (see README): create a KV namespace, set RESEND_API_KEY as a secret, deploy.
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "POST" && url.pathname === "/beat") {
      const body = await request.json().catch(() => ({}));
      const device = (body.device || "unknown").slice(0, 64);
      const record = {
        ts: Date.now(),
        service_running: body.service_running !== false,
        device,
        warned: false,
      };
      await env.GUARDIAN_KV.put("hb:" + device, JSON.stringify(record));
      return Response.json({ ok: true });
    }

    if (url.pathname === "/status") {
      const list = await env.GUARDIAN_KV.list({ prefix: "hb:" });
      const out = [];
      for (const k of list.keys) out.push(JSON.parse(await env.GUARDIAN_KV.get(k.name)));
      return Response.json(out);
    }

    return new Response("Guardian heartbeat worker is running.", { status: 200 });
  },

  async scheduled(event, env, ctx) {
    const graceMs = parseInt(env.GRACE_MINUTES || "60", 10) * 60 * 1000;
    const now = Date.now();
    const list = await env.GUARDIAN_KV.list({ prefix: "hb:" });

    for (const k of list.keys) {
      const rec = JSON.parse(await env.GUARDIAN_KV.get(k.name));
      const silentMin = Math.floor((now - rec.ts) / 60000);

      if (now - rec.ts > graceMs && !rec.warned && env.ALERT_EMAIL) {
        await sendEmail(
          env,
          env.ALERT_EMAIL,
          "[Guardian] Device went silent — possible uninstall/tamper",
          `No heartbeat from '${rec.device}' for ${silentMin} minutes. ` +
            `Guardian may have been uninstalled, force-stopped, or the device powered off.`
        );
        rec.warned = true;
        await env.GUARDIAN_KV.put(k.name, JSON.stringify(rec));
      }
    }
  },
};

async function sendEmail(env, to, subject, text) {
  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.RESEND_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      from: env.RESEND_FROM || "Guardian <onboarding@resend.dev>",
      to: [to],
      subject,
      text,
    }),
  });
  if (!resp.ok) console.log("Resend error", resp.status, await resp.text());
}
