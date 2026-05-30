/**
 * TrumpTruthTrading — Cloudflare Worker proxy
 *
 * Forwards requests to Truth Social's API using Cloudflare's edge IPs,
 * bypassing the IP-level block that GitHub Actions (AWS/Azure) receives.
 *
 * Deploy at: https://dash.cloudflare.com → Workers & Pages → Create Worker
 * Paste this script, click Deploy, copy the *.workers.dev URL.
 * Then add that URL as GitHub Secret: TRUTH_SOCIAL_PROXY_URL
 */

const TARGET = "https://truthsocial.com";

const FORWARD_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  Accept: "application/json",
};

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const targetUrl = TARGET + url.pathname + url.search;

    const response = await fetch(targetUrl, {
      method: request.method,
      headers: FORWARD_HEADERS,
    });

    const body = await response.arrayBuffer();
    return new Response(body, {
      status: response.status,
      headers: {
        "Content-Type":
          response.headers.get("Content-Type") ?? "application/json",
        "Access-Control-Allow-Origin": "*",
      },
    });
  },
};
