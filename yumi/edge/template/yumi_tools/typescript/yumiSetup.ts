/**
 * Yumi Edge — TypeScript tool registration
 *
 * Register your functions with `agent.register()` and call `initYumi()`
 * from your app entry point.
 *
 *     import { initYumi } from "./yumi_tools/typescript/yumiSetup";
 *     initYumi();
 *
 * Quick test: ``npx tsx yumiSetup.ts`` (from yumi_tools/typescript/)
 *
 * Requires: npm install (from the yumi_tools/typescript/yumi_sdk directory)
 */

import path from "node:path";
import { pathToFileURL } from "node:url";

import { YumiAgent } from "./yumi_sdk/src";

// ── Connection (edit here, or set in .env) ──

const YUMI_CONNECTION_CODE = "yumi-lan_..."; // paste from `yumi --server`
const YUMI_EDGE_NAME = "My Node App";

export function initYumi(): YumiAgent {
  const agent = new YumiAgent({
    connectionCode: YUMI_CONNECTION_CODE,
    edgeName: YUMI_EDGE_NAME,
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

  // Dangerous tools: user confirms in the Yumi web UI or `yumi --chat` (not on device):
  // agent.register({
  //   name: "delete_all",
  //   description: "Delete all data",
  //   requireConfirmation: true,
  //   handler: async () => "Deleted everything",
  // });

  agent.runInBackground();
  return agent;
}

/** True when this file is executed directly (e.g. `npx tsx yumiSetup.ts`). */
function isDirectRun(): boolean {
  if (typeof process === "undefined" || !process.argv[1]) {
    return false;
  }
  return import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
}

if (isDirectRun()) {
  initYumi();
  console.log("Yumi edge running (yumiSetup as entry). Press Ctrl+C to stop.");
}
