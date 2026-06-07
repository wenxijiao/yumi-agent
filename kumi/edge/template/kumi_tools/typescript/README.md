# Kumi Edge — TypeScript / JavaScript

Use this when your app runs in Node.js or in the browser and you want to expose functions to Kumi.

The SDK is **isomorphic**:

- **Browser**: uses native `WebSocket`
- **Node.js**: uses the `ws` package through dynamic import

## Quick Start

1. Install dependencies:

```bash
cd kumi_tools/typescript/kumi_sdk
npm install
```

2. Edit `kumi_tools/typescript/kumiSetup.ts`
3. Set your connection code in code or in `kumi_tools/.env`
4. Either call `initKumi()` from your app, **or** run the setup file alone (no separate `main.ts`):

```bash
cd kumi_tools/typescript
npx tsx kumiSetup.ts
```

The file detects direct execution and calls `initKumi()` for you.

## Files In This Folder

```text
kumi_tools/typescript/
├── README.md
├── kumiSetup.ts           # edit this
└── kumi_sdk/              # bundled SDK
    ├── package.json
    ├── tsconfig.json
    └── src/
```

## Configure Connection

### Option A: in code

Edit the constants in `kumiSetup.ts`.

### Option B: `.env`

```env
KUMI_CONNECTION_CODE=kumi-lan_...
EDGE_NAME=My App
```

In browsers, `.env` loading is skipped automatically. Pass `connectionCode` and `edgeName` directly to `new KumiAgent(...)` instead, or inject them at build time.

## Register Tools

```ts
agent.register({
  name: "set_light",
  description: "Control room lights",
  parameters: [
    { name: "room", type: "string", description: "Room name" },
    { name: "on", type: "boolean", description: "Turn on or off" },
  ],
  handler: async (args) => {
    const room = args.string("room") ?? "living_room";
    const on = args.bool("on") ?? false;
    return `Light in ${room}: ${on}`;
  },
});
```

Use `requireConfirmation: true` for irreversible tools.

## Start It From Your App

TypeScript:

```ts
import { initKumi } from "./kumi_tools/typescript/kumiSetup";

initKumi();
```

JavaScript:

```js
const { initKumi } = require("./kumi_tools/typescript/kumiSetup");

initKumi();
```

## Browser Notes

- No top-level `fs`, `path`, `os`, or `ws` imports, so browser bundlers can import the SDK cleanly
- Confirmation policy is memory-only in the browser
- Relay bootstrap uses `fetch`

## Node Notes

- `npm install` pulls in `ws`
- `.env` loading and confirmation-policy file persistence work normally on disk
