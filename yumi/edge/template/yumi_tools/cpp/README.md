# Yumi Edge — C / C++

Use this when your host app is written in C or C++ and you want to expose functions to Yumi.

The C++ SDK is now **header-only** at the core, with a pluggable transport interface.

## Quick Start

1. Add the bundled `YumiSDK/` directory to your CMake project
2. Edit `yumi_tools/cpp/yumi_setup.cpp`
3. Call `initYumi()` from your real app entry point
4. Build your app as usual

## Requirements

- CMake 3.14+
- C++17 compiler
- Internet access on the first CMake configure, because dependencies are fetched automatically

Fetched dependencies:

- `nlohmann/json`
- `IXWebSocket` for the default transport

The default CMake configuration builds without TLS/zlib so a clean local
toolchain can compile the SDK for `ws://` connections. If your connection code
resolves to `wss://`, configure CMake with `-DYUMI_USE_TLS=ON` and provide the
TLS backend required by IXWebSocket.

## Files In This Folder

```text
yumi_tools/cpp/
├── README.md
├── yumi_setup.cpp         # edit this
└── YumiSDK/
    ├── CMakeLists.txt
    ├── include/yumi/
    │   ├── yumi_agent.hpp
    │   ├── yumi_agent.h
    │   ├── tool_arguments.hpp
    │   └── tool_parameter.hpp
    └── src/
        └── c_api.cpp
```

## Add It To Your Build

```cmake
add_subdirectory(yumi_tools/cpp/YumiSDK)
target_link_libraries(your_app PRIVATE yumi_sdk)
```

Then build normally:

```bash
mkdir build
cd build
cmake ..
cmake --build .
```

## Configure Connection

The simplest path is to edit the constants in `yumi_setup.cpp`.

You can also use `yumi_tools/.env`:

```env
YUMI_CONNECTION_CODE=yumi-lan_...
EDGE_NAME=My Device
```

## Register Tools (C++)

```cpp
yumi::RegisterOptions setLightOpts;
setLightOpts.name = "set_light";
setLightOpts.description = "Control room lights";
setLightOpts.parameters = {
    {"room", "string", "Room name"},
    {"on", "boolean", "Turn on or off"},
};
setLightOpts.handler = [](const yumi::ToolArguments& args) -> std::string {
    auto room = args.string("room").value_or("living_room");
    auto on = args.boolean("on").value_or(false);
    return setLight(room, on);
};
agent->registerTool(std::move(setLightOpts));
```

Use `requireConfirmation = true` for dangerous tools.

## Custom Transport

For most users, `YumiAgent(code)` or `YumiAgent(code, edgeName)` uses the default IXWebSocket-based transport.

Advanced users can inject their own transport:

```cpp
std::shared_ptr<yumi::IYumiTransport> transport = ...;
yumi::YumiAgent agent("yumi-lan_...", transport);
```

This is the intended path for engines such as UE5 or for environments with a custom networking stack.

## C API

If you need C, FFI, or another language binding, use:

```c
#include <yumi/yumi_agent.h>
```

The `yumi_sdk` library target includes the C ABI wrapper.
