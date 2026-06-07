/**
 * Auth / LAN decode / relay bootstrap — works in browser (fetch, atob) and Node (fetch on 18+).
 */

import { setRelayFromBootstrap } from "./runtime";

const TOKEN_PREFIX = "kumi_";
const LAN_TOKEN_PREFIX = "kumi-lan_";
const LEGACY_LAN_PREFIXES = ["ml1_", "kumi_lan_"];

/** Base64url → UTF-8 string without Node Buffer (browser-safe). */
function b64urlToUtf8(data: string): string {
  const padding = (4 - (data.length % 4)) % 4;
  const b64 = data.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat(padding);
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new TextDecoder("utf-8").decode(bytes);
}

export interface LanCodeResult {
  host: string;
  port: number;
}

export function decodeLanCode(token: string): LanCodeResult {
  let encoded: string;

  if (token.startsWith(LAN_TOKEN_PREFIX)) {
    encoded = token.slice(LAN_TOKEN_PREFIX.length);
  } else {
    const prefix = LEGACY_LAN_PREFIXES.find((p) => token.startsWith(p));
    if (prefix) {
      encoded = token.slice(prefix.length);
    } else {
      throw new Error("Invalid Kumi LAN code prefix.");
    }
  }

  const data = JSON.parse(b64urlToUtf8(encoded));

  let host: string;
  let port: number;

  if (data.h) {
    host = String(data.h);
    port = data.p != null ? Number(data.p) : 8000;
  } else if (data.base_url) {
    const url = new URL(data.base_url);
    if (!url.hostname) throw new Error("LAN code missing host.");
    host = url.hostname;
    port = url.port ? Number(url.port) : 8000;
  } else {
    throw new Error("LAN code missing host.");
  }

  if (data.x && Number(data.x) < Math.floor(Date.now() / 1000)) {
    throw new Error("LAN code has expired.");
  }

  return { host, port };
}

export function decodeCredential(token: string): Record<string, unknown> {
  if (!token.startsWith(TOKEN_PREFIX)) {
    throw new Error("Invalid Kumi credential prefix.");
  }
  return JSON.parse(b64urlToUtf8(token.slice(TOKEN_PREFIX.length)));
}

export interface BootstrapResult {
  relayUrl: string;
  accessToken: string;
}

export async function bootstrapProfile(
  joinCode: string,
  scope: string,
  deviceName: string = ""
): Promise<BootstrapResult> {
  const cred = decodeCredential(joinCode);
  const relayUrl = String(cred.relay_url).replace(/\/+$/, "");
  const url = `${relayUrl}/v1/bootstrap`;

  const payload = JSON.stringify({
    join_code: joinCode,
    scope,
    device_name: deviceName.trim(),
  });

  if (typeof globalThis.fetch !== "function") {
    throw new Error(
      "Kumi SDK: global fetch is not available. Use Node.js 18+ or a browser, or set KUMI_RELAY_URL + KUMI_ACCESS_TOKEN."
    );
  }

  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), 15000);

  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(t);
  }

  const body = await res.text();
  if (!res.ok) {
    throw new Error(`Bootstrap failed: ${body || res.statusText}`);
  }

  let data: { access_token?: string };
  try {
    data = JSON.parse(body) as { access_token?: string };
  } catch {
    throw new Error("Bootstrap failed: invalid JSON response");
  }

  const at = data.access_token;
  if (typeof at !== "string" || !at) {
    throw new Error("Bootstrap response missing access_token.");
  }

  setRelayFromBootstrap(relayUrl, at);

  return { relayUrl, accessToken: at };
}

export function isLanCode(code: string): boolean {
  return (
    code.startsWith(LAN_TOKEN_PREFIX) ||
    LEGACY_LAN_PREFIXES.some((p) => code.startsWith(p))
  );
}

export function isRelayToken(code: string): boolean {
  return code.startsWith(TOKEN_PREFIX) && !isLanCode(code);
}

export function parseLanCode(code: string): string {
  const { host, port } = decodeLanCode(code);
  return `http://${host}:${port}`;
}
