# Kumi Edge — C / C++

Use this when your host app is written in C or C++ and you want to expose functions to Kumi.

The C++ SDK is now **header-only** at the core, with a pluggable transport interface.

## Quick Start

1. Add the bundled `KumiSDK/` directory to your CMake project
2. Edit `kumi_tools/cpp/kumi_setup.cpp`
3. Call `initKumi()` from your real app entry point
4. Build your app as usual

## Requirements

- CMake 3.14+
- C++17 compiler
- Internet access on the first CMake configure, because dependencies are fetched automatically

Fetched dependencies:

- `nlohmann/json`
- `IXWebSocket` for the default transport

## Files In This Folder

```text
kumi_tools/cpp/
├── README.md
├── kumi_setup.cpp         # edit this
└── KumiSDK/
    ├── CMakeLists.txt
    ├── include/kumi/
    │   ├── kumi_agent.hpp
    │   ├── kumi_agent.h
    │   ├── tool_arguments.hpp
    │   └── tool_parameter.hpp
    └── src/
        └── c_api.cpp
```

## Add It To Your Build

```cmake
add_subdirectory(kumi_tools/cpp/KumiSDK)
target_link_libraries(your_app PRIVATE kumi_sdk)
```

Then build normally:

```bash
mkdir build
cd build
cmake ..
cmake --build .
```

## Configure Connection

The simplest path is to edit the constants in `kumi_setup.cpp`.

You can also use `kumi_tools/.env`:

```env
KUMI_CONNECTION_CODE=kumi-lan_...
EDGE_NAME=My Device
```

## Register Tools (C++)

```cpp
agent->registerTool({
    .name = "set_light",
    .description = "Control room lights",
    .parameters = {
        {"room", "string", "Room name"},
        {"on", "boolean", "Turn on or off"},
    },
    .handler = [](const kumi::ToolArguments& args) -> std::string {
        auto room = args.string("room").value_or("living_room");
        auto on = args.boolean("on").value_or(false);
        return setLight(room, on);
    },
});
```

Use `requireConfirmation = true` for dangerous tools.

## Custom Transport

For most users, `KumiAgent(code)` or `KumiAgent(code, edgeName)` uses the default IXWebSocket-based transport.

Advanced users can inject their own transport:

```cpp
std::shared_ptr<kumi::IKumiTransport> transport = ...;
kumi::KumiAgent agent("kumi-lan_...", transport);
```

This is the intended path for engines such as UE5 or for environments with a custom networking stack.

## C API

If you need C, FFI, or another language binding, use:

```c
#include <kumi/kumi_agent.h>
```

The `kumi_sdk` library target includes the C ABI wrapper.
