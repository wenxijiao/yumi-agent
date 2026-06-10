# Yumi Edge — TypeScript / JavaScript

Use this when your app runs in Node.js or in the browser and you want to expose functions to Yumi.

The SDK is **isomorphic**:

- **Browser**: uses native `WebSocket`
- **Node.js**: uses the `ws` package through dynamic import

## Quick Start

1. Install dependencies:

```bash
cd yumi_tools/typescript/yumi_sdk
npm install
```

2. Edit `yumi_tools/typescript/yumiSetup.ts`
3. Set your connection code in code or in `yumi_tools/.env`
4. Either call `initYumi()` from your app, **or** run the setup file alone (no separate `main.ts`):

```bash
cd yumi_tools/typescript
npx tsx yumiSetup.ts
```

The file detects direct execution and calls `initYumi()` for you.

## Files In This Folder

```text
yumi_tools/typescript/
├── README.md
├── yumiSetup.ts           # edit this
└── yumi_sdk/              # bundled SDK
    ├── package.json
    ├── tsconfig.json
    └── src/
```

## Configure Connection

### Option A: in code

Edit the constants in `yumiSetup.ts`.

### Option B: `.env`

```env
YUMI_CONNECTION_CODE=yumi-lan_...
EDGE_NAME=My App
```

In browsers, `.env` loading is skipped automatically. Pass `connectionCode` and `edgeName` directly to `new YumiAgent(...)` instead, or inject them at build time.

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
import { initYumi } from "./yumi_tools/typescript/yumiSetup";

initYumi();
```

JavaScript:

```js
const { initYumi } = require("./yumi_tools/typescript/yumiSetup");

initYumi();
```

## Browser Notes

- No top-level `fs`, `path`, `os`, or `ws` imports, so browser bundlers can import the SDK cleanly
- Confirmation policy is memory-only in the browser
- Network calls use `fetch`

## Node Notes

- `npm install` pulls in `ws`
- `.env` loading and confirmation-policy file persistence work normally on disk
