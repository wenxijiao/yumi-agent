import { bootstrapProfile, isLanCode, isRelayToken, parseLanCode } from "./auth";
import { getKumiEnv } from "./runtime";

export interface ConnectionConfig {
  mode: "direct" | "relay";
  baseUrl: string;
  accessToken?: string;
}

export function httpToWs(url: string): string {
  if (url.startsWith("https://")) return "wss://" + url.slice("https://".length);
  if (url.startsWith("http://")) return "ws://" + url.slice("http://".length);
  return url;
}

export function relayEdgeWsUrl(config: ConnectionConfig): string {
  return httpToWs(config.baseUrl.replace(/\/+$/, "")) + "/ws/edge";
}

export async function resolveConnection(
  code: string | undefined,
  edgeName: string,
  env: Record<string, string | undefined> = getKumiEnv()
): Promise<ConnectionConfig> {
  const relayUrl = env.KUMI_RELAY_URL;
  const accessToken = env.KUMI_ACCESS_TOKEN;
  if (relayUrl && accessToken) {
    return {
      mode: "relay",
      baseUrl: relayUrl.replace(/\/+$/, ""),
      accessToken,
    };
  }

  const c = code ?? "";

  if (c.startsWith("ws://") || c.startsWith("wss://")) {
    return { mode: "direct", baseUrl: c };
  }

  if (isLanCode(c)) {
    const serverUrl = parseLanCode(c);
    const wsUrl = httpToWs(serverUrl.replace(/\/+$/, "")) + "/ws/edge";
    return { mode: "direct", baseUrl: wsUrl };
  }

  if (isRelayToken(c)) {
    const profile = await bootstrapProfile(c, "edge", edgeName);
    return {
      mode: "relay",
      baseUrl: profile.relayUrl,
      accessToken: profile.accessToken,
    };
  }

  if (c.startsWith("http://") || c.startsWith("https://")) {
    const wsUrl = httpToWs(c.replace(/\/+$/, "")) + "/ws/edge";
    return { mode: "direct", baseUrl: wsUrl };
  }

  return { mode: "direct", baseUrl: "ws://127.0.0.1:8000/ws/edge" };
}
