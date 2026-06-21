cmake_minimum_required(VERSION 3.14)
project(YumiSDK VERSION 0.1.0 LANGUAGES CXX)

if(NOT DEFINED CMAKE_CXX_STANDARD)
    set(CMAKE_CXX_STANDARD 17)
elseif(CMAKE_CXX_STANDARD LESS 17)
    message(FATAL_ERROR "YumiSDK requires C++17 or later.")
endif()
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(YUMI_BUILD_EXAMPLES "Build example programs" OFF)
option(YUMI_USE_TLS "Enable TLS (wss://) support via IXWebSocket" OFF)
option(YUMI_USE_ZLIB "Enable zlib compression support via IXWebSocket" OFF)

include(FetchContent)

# nlohmann/json — header-only JSON library
FetchContent_Declare(
    nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG        v3.11.3
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(nlohmann_json)

# IXWebSocket — used by DefaultTransport in yumi_agent.hpp (FetchContent exposes headers to consumers)
set(USE_TLS ${YUMI_USE_TLS} CACHE BOOL "" FORCE)
set(USE_ZLIB ${YUMI_USE_ZLIB} CACHE BOOL "" FORCE)
FetchContent_Declare(
    ixwebsocket
    GIT_REPOSITORY https://github.com/machinezone/IXWebSocket.git
    GIT_TAG        v11.4.5
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(ixwebsocket)

# C++ core is header-only (yumi_agent.hpp). This target links the C ABI shim only.
add_library(yumi_sdk STATIC src/c_api.cpp)

target_include_directories(yumi_sdk
    PUBLIC  ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_link_libraries(yumi_sdk
    PUBLIC  nlohmann_json::nlohmann_json
            ixwebsocket
)

if(YUMI_BUILD_EXAMPLES AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/examples/basic_usage.cpp")
    add_executable(yumi_example examples/basic_usage.cpp)
    target_link_libraries(yumi_example PRIVATE yumi_sdk)
endif()
