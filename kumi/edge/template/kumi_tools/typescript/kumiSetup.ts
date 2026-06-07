/**
 * Kumi Edge — TypeScript tool registration
 *
 * Register your functions with `agent.register()` and call `initKumi()`
 * from your app entry point.
 *
 *     import { initKumi } from "./kumi_tools/typescript/kumiSetup";
 *     initKumi();
 *
 * Quick test: ``npx tsx kumiSetup.ts`` (from kumi_tools/typescript/)
 *
 * Requires: npm install (from the kumi_tools/typescript/kumi_sdk directory)
 */

import path from "node:path";
import { pathToFileURL } from "node:url";

import { KumiAgent } from "./kumi_sdk/src";

// ── Connection (edit here, or set in .env) ──

const KUMI_CONNECTION_CODE = "kumi-lan_..."; // paste from `kumi --server`, or kumi_... for relay
const KUMI_EDGE_NAME = "My Node App";

export function initKumi(): KumiAgent {
  const agent = new KumiAgent({
    connectionCode: KUMI_CONNECTION_CODE,
    edgeName: KUMI_EDGE_NAME,
  });

  // ── Register tools: name + description + parameters + handler ──

  // agent.register({
  //   name: "jump",
  //   description: "Make the character jump",
  //   parameters: [
  //     { name: "height", type: "number", description: "Jump height in meters" },
  //   ],
  //   handler: async (args) => {
  //     const height = args.number("height") ?? 1.0;
  //     return `Jumped ${height} meters`;
  //   },
  // });

  // Dangerous tools: user confirms in the Kumi web UI or `kumi --chat` (not on device):
  // agent.register({
  //   name: "delete_all",
  //   description: "Delete all data",
  //   requireConfirmation: true,
  //   handler: async () => "Deleted everything",
  // });

  agent.runInBackground();
  return agent;
}

/** True when this file is executed directly (e.g. `npx tsx kumiSetup.ts`). */
function isDirectRun(): boolean {
  if (typeof process === "undefined" || !process.argv[1]) {
    return false;
  }
  return import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
}

if (isDirectRun()) {
  initKumi();
  console.log("Kumi edge running (kumiSetup as entry). Press Ctrl+C to stop.");
}
