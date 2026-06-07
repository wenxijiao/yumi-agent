/**
 * @file yumi_agent.hpp
 * @brief Header-only Yumi Edge SDK — core logic + pluggable transport.
 *
 * ## Batteries included, but pluggable
 * - **IYumiTransport** — abstract WebSocket surface; inject for UE5 / custom stacks.
 * - **DefaultTransport** — when `ixwebsocket/IXWebSocket.h` is on the include path
 *   (and you link IXWebSocket), the default ctor uses it. Define **YUMI_SDK_NO_IXWEBSOCKET**
 *   before including this header to force custom transport only.
 *
 * ## Dependencies
 * - [nlohmann/json](https://github.com/nlohmann/json) (header-only)
 * - Optional: [IXWebSocket](https://github.com/machinezone/IXWebSocket) for DefaultTransport
 *
 * ## Constructors
 * - `YumiAgent(std::string code)` — creates `DefaultTransport` internally (requires IXWebSocket).
 * - `YumiAgent(std::string code, std::shared_ptr<IYumiTransport> transport)` — custom transport.
 *
 * C++17 or later.
 */
#pragma once

#include <nlohmann/json.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#undef min
#undef max
#include <direct.h>
#else
#include <unistd.h>
#endif

// ── IXWebSocket availability (default: use if present) ─────────────────────

#if !defined(YUMI_SDK_NO_IXWEBSOCKET)
#if defined(__has_include)
#if __has_include(<ixwebsocket/IXWebSocket.h>)
#include <ixwebsocket/IXWebSocket.h>
#define YUMI_SDK_IXWEBSOCKET_AVAILABLE 1
#endif
#endif
#endif

namespace yumi {

// ═══════════════════════════════════════════════════════════════════════════
//  Tool schema & arguments (same wire format as other language SDKs)
// ═══════════════════════════════════════════════════════════════════════════

struct ToolParameter {
    std::string name;
    std::string type;        // "string", "integer", "number", "boolean", "array", "object"
    std::string description;
    bool required = true;
};

inline nlohmann::json buildToolSchema(
    const std::string& name,
    const std::string& description,
    const std::vector<ToolParameter>& parameters,
    bool requireConfirmation = false,
    int timeout = 0,
    bool alwaysInclude = false,
    bool allowProactive = false,
    bool proactiveContext = false,
    nlohmann::json proactiveContextArgs = nullptr,
    std::string proactiveContextDescription = ""
) {
    nlohmann::json properties = nlohmann::json::object();
    std::vector<std::string> requiredParams;

    for (const auto& p : parameters) {
        properties[p.name] = {
            {"type", p.type},
            {"description", p.description}
        };
        if (p.required) {
            requiredParams.push_back(p.name);
        }
    }

    nlohmann::json schema = {
        {"type", "function"},
        {"function", {
            {"name", name},
            {"description", description},
            {"parameters", {
                {"type", "object"},
                {"properties", properties},
                {"required", requiredParams}
            }}
        }}
    };

    if (timeout > 0) {
        schema["timeout"] = timeout;
    }
    if (requireConfirmation) {
        schema["require_confirmation"] = true;
    }
    if (alwaysInclude) {
        schema["always_include"] = true;
    }
    if (allowProactive) {
        schema["allow_proactive"] = true;
    }
    if (proactiveContext) {
        schema["proactive_context"] = true;
    }
    if (!proactiveContextArgs.is_null()) {
        schema["proactive_context_args"] = proactiveContextArgs;
    }
    if (!proactiveContextDescription.empty()) {
        schema["proactive_context_description"] = proactiveContextDescription;
    }

    return schema;
}

class ToolArguments {
public:
    explicit ToolArguments(nlohmann::json raw) : raw_(std::move(raw)) {}

    const nlohmann::json& rawData() const { return raw_; }

    std::optional<std::string> string(const std::string& key) const {
        auto it = raw_.find(key);
        if (it != raw_.end() && it->is_string())
            return it->get<std::string>();
        return std::nullopt;
    }

    std::optional<int> integer(const std::string& key) const {
        auto it = raw_.find(key);
        if (it != raw_.end() && it->is_number_integer())
            return it->get<int>();
        return std::nullopt;
    }

    std::optional<double> number(const std::string& key) const {
        auto it = raw_.find(key);
        if (it != raw_.end() && it->is_number())
            return it->get<double>();
        return std::nullopt;
    }

    std::optional<bool> boolean(const std::string& key) const {
        auto it = raw_.find(key);
        if (it != raw_.end() && it->is_boolean())
            return it->get<bool>();
        return std::nullopt;
    }

private:
    nlohmann::json raw_;
};

using ToolHandler = std::function<std::string(const ToolArguments&)>;

struct RegisterOptions {
    std::string name;
    std::string description;
    std::vector<ToolParameter> parameters;
    ToolHandler handler;
    int timeout = 0;
    bool requireConfirmation = false;
    bool alwaysInclude = false;
    bool allowProactive = false;
    bool proactiveContext = false;
    nlohmann::json proactiveContextArgs = nullptr;
    std::string proactiveContextDescription;
};

// ═══════════════════════════════════════════════════════════════════════════
//  Transport — core decoupled from sockets
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Abstract WebSocket transport. Implement for UE5 IWebSocket, custom TLS, mocks, etc.
 *
 * Contract (mirrors typical client WebSocket APIs):
 * - Call **setUrl** then **setHandlers** then **start**. Callbacks may run on a worker thread.
 * - **sendText** must be safe to call from handler threads (implementation-defined).
 * - **stop** closes the connection; **start** may be called again after **stop** for reconnect.
 */
class IYumiTransport {
public:
    virtual ~IYumiTransport() = default;

    virtual void setUrl(std::string url) = 0;

    virtual void setHandlers(
        std::function<void()> onOpen,
        std::function<void(std::string_view text)> onText,
        std::function<void()> onClosed,
        std::function<void(std::string error)> onError
    ) = 0;

    virtual void start() = 0;
    virtual void stop() = 0;

    /** Send a UTF-8 text frame (JSON payloads). Returns false if not connected. */
    virtual bool sendText(std::string_view utf8) = 0;
};

#if defined(YUMI_SDK_IXWEBSOCKET_AVAILABLE)

/**
 * Default transport: thin header-only wrapper around IXWebSocket::WebSocket.
 * Link **ixwebsocket** in your build (CMake target or equivalent).
 */
class DefaultTransport final : public IYumiTransport {
public:
    void setUrl(std::string url) override {
        if (!ws_) {
            ws_ = std::make_unique<ix::WebSocket>();
        }
        ws_->setUrl(std::move(url));
        ws_->setHandshakeTimeout(10);
    }

    void setHandlers(
        std::function<void()> onOpen,
        std::function<void(std::string_view text)> onText,
        std::function<void()> onClosed,
        std::function<void(std::string error)> onError
    ) override {
        onOpen_ = std::move(onOpen);
        onText_ = std::move(onText);
        onClosed_ = std::move(onClosed);
        onError_ = std::move(onError);

        if (!ws_) return;
        ws_->setOnMessageCallback([this](const ix::WebSocketMessagePtr& msg) {
            switch (msg->type) {
                case ix::WebSocketMessageType::Open:
                    if (onOpen_) onOpen_();
                    break;
                case ix::WebSocketMessageType::Message:
                    if (onText_) onText_(msg->str);
                    break;
                case ix::WebSocketMessageType::Close:
                    if (onClosed_) onClosed_();
                    break;
                case ix::WebSocketMessageType::Error:
                    if (onError_) onError_(msg->errorInfo.reason);
                    break;
                default:
                    break;
            }
        });
    }

    void start() override {
        if (!ws_) {
            throw std::runtime_error("DefaultTransport::start: setUrl was not called");
        }
        ws_->start();
    }

    void stop() override {
        if (ws_) {
            ws_->stop();
            ws_.reset();
        }
    }

    bool sendText(std::string_view utf8) override {
        if (!ws_) return false;
        return ws_->sendUtf8Text(std::string(utf8)).success;
    }

private:
    std::unique_ptr<ix::WebSocket> ws_;
    std::function<void()> onOpen_;
    std::function<void(std::string_view)> onText_;
    std::function<void()> onClosed_;
    std::function<void(std::string)> onError_;
};

#else

/**
 * Stub when IXWebSocket headers are not available. **start()** throws.
 * Use `YumiAgent(code, yourTransport)` with a custom **IYumiTransport**.
 */
class DefaultTransport final : public IYumiTransport {
public:
    void setUrl(std::string) override {}
    void setHandlers(
        std::function<void()>,
        std::function<void(std::string_view)>,
        std::function<void()>,
        std::function<void(std::string)>
    ) override {}
    void start() override {
        throw std::runtime_error(
            "Yumi DefaultTransport: IXWebSocket not available at compile time. "
            "Add ixwebsocket to your include path, remove YUMI_SDK_NO_IXWEBSOCKET, "
            "link ixwebsocket, or use YumiAgent(code, std::shared_ptr<IYumiTransport>)."
        );
    }
    void stop() override {}
    bool sendText(std::string_view) override { return false; }
};

#endif // YUMI_SDK_IXWEBSOCKET_AVAILABLE

// ═══════════════════════════════════════════════════════════════════════════
//  Internal: env, auth, connection (inlined)
// ═══════════════════════════════════════════════════════════════════════════

namespace detail {

inline std::string trim(const std::string& s) {
    auto start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    auto end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end - start + 1);
}

inline void loadEnvFile(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) return;

    std::string line;
    while (std::getline(file, line)) {
        std::string trimmed = trim(line);
        if (trimmed.empty() || trimmed[0] == '#') continue;

        auto eqPos = trimmed.find('=');
        if (eqPos == std::string::npos) continue;

        std::string key = trim(trimmed.substr(0, eqPos));
        std::string value = trim(trimmed.substr(eqPos + 1));

        if (value.size() >= 2) {
            if ((value.front() == '"' && value.back() == '"') ||
                (value.front() == '\'' && value.back() == '\'')) {
                value = value.substr(1, value.size() - 2);
            }
        }

        if (!std::getenv(key.c_str())) {
#ifdef _WIN32
            _putenv_s(key.c_str(), value.c_str());
#else
            setenv(key.c_str(), value.c_str(), 0);
#endif
        }
    }
}

inline std::string getenvStr(const char* name) {
    const char* v = std::getenv(name);
    return v ? std::string(v) : std::string();
}

// ── base64url (LAN / credential tokens) ─────────────────────────────────────

inline std::string b64urlDecode(const std::string& data) {
    static const int B64_TABLE[256] = {
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,62,-1,62,-1,63,
        52,53,54,55,56,57,58,59,60,61,-1,-1,-1,-1,-1,-1,
        -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9,10,11,12,13,14,
        15,16,17,18,19,20,21,22,23,24,25,-1,-1,-1,-1,63,
        -1,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,
        41,42,43,44,45,46,47,48,49,50,51,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    };

    std::string input = data;
    std::replace(input.begin(), input.end(), '-', '+');
    std::replace(input.begin(), input.end(), '_', '/');
    while (input.size() % 4 != 0) input += '=';

    std::string result;
    result.reserve(input.size() * 3 / 4);

    int val = 0, bits = -8;
    for (unsigned char c : input) {
        if (B64_TABLE[c] == -1) continue;
        val = (val << 6) + B64_TABLE[c];
        bits += 6;
        if (bits >= 0) {
            result.push_back(static_cast<char>((val >> bits) & 0xFF));
            bits -= 8;
        }
    }
    return result;
}

inline const std::string TOKEN_PREFIX = "yumi_";
inline const std::string LAN_TOKEN_PREFIX = "yumi-lan_";
inline const char* LEGACY_LAN_PREFIXES[] = {"ml1_", "yumi_lan_"};
inline constexpr size_t LEGACY_LAN_COUNT = 2;

struct LanCodeResult {
    std::string host;
    int port;
};

inline LanCodeResult decodeLanCode(const std::string& token) {
    std::string encoded;
    if (token.compare(0, LAN_TOKEN_PREFIX.size(), LAN_TOKEN_PREFIX) == 0) {
        encoded = token.substr(LAN_TOKEN_PREFIX.size());
    } else {
        bool matched = false;
        for (size_t i = 0; i < LEGACY_LAN_COUNT; ++i) {
            std::string prefix(LEGACY_LAN_PREFIXES[i]);
            if (token.compare(0, prefix.size(), prefix) == 0) {
                encoded = token.substr(prefix.size());
                matched = true;
                break;
            }
        }
        if (!matched) {
            throw std::runtime_error("Invalid Yumi LAN code prefix.");
        }
    }

    auto data = nlohmann::json::parse(b64urlDecode(encoded));

    std::string host;
    int port = 8000;

    if (data.contains("h")) {
        host = data["h"].get<std::string>();
        if (data.contains("p")) port = data["p"].get<int>();
    } else if (data.contains("base_url")) {
        std::string baseUrl = data["base_url"].get<std::string>();
        auto schemeEnd = baseUrl.find("://");
        std::string hostPort = (schemeEnd != std::string::npos)
            ? baseUrl.substr(schemeEnd + 3) : baseUrl;
        auto slashPos = hostPort.find('/');
        if (slashPos != std::string::npos) hostPort = hostPort.substr(0, slashPos);

        auto colonPos = hostPort.rfind(':');
        if (colonPos != std::string::npos) {
            host = hostPort.substr(0, colonPos);
            port = std::stoi(hostPort.substr(colonPos + 1));
        } else {
            host = hostPort;
        }
        if (host.empty()) throw std::runtime_error("LAN code missing host.");
    } else {
        throw std::runtime_error("LAN code missing host.");
    }

    if (data.contains("x") && data["x"].get<int64_t>() != 0) {
        auto now = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()
        ).count();
        if (data["x"].get<int64_t>() < now) {
            throw std::runtime_error("LAN code has expired.");
        }
    }

    return {host, port};
}

inline nlohmann::json decodeCredential(const std::string& token) {
    if (token.compare(0, TOKEN_PREFIX.size(), TOKEN_PREFIX) != 0) {
        throw std::runtime_error("Invalid Yumi credential prefix.");
    }
    return nlohmann::json::parse(b64urlDecode(token.substr(TOKEN_PREFIX.size())));
}

struct BootstrapResult {
    std::string relayUrl;
    std::string accessToken;
};

#if !defined(_WIN32)
#include <sys/socket.h>
#include <netdb.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#endif

inline std::string httpPost(const std::string& url, const std::string& body, int timeoutSec = 15) {
    bool useTls = false;
    std::string hostPort, path;
    if (url.compare(0, 8, "https://") == 0) {
        useTls = true;
        hostPort = url.substr(8);
    } else if (url.compare(0, 7, "http://") == 0) {
        hostPort = url.substr(7);
    } else {
        throw std::runtime_error("Unsupported URL scheme");
    }

    if (useTls) {
        throw std::runtime_error(
            "HTTPS bootstrap is not supported in this minimal HTTP client. "
            "Set YUMI_RELAY_URL and YUMI_ACCESS_TOKEN, or use an HTTP relay URL."
        );
    }

#ifdef _WIN32
    WSADATA wsaData;
    WSAStartup(MAKEWORD(2, 2), &wsaData);
#endif

    auto pathPos = hostPort.find('/');
    if (pathPos != std::string::npos) {
        path = hostPort.substr(pathPos);
        hostPort = hostPort.substr(0, pathPos);
    } else {
        path = "/";
    }

    std::string host;
    int port = 80;
    auto colonPos = hostPort.rfind(':');
    if (colonPos != std::string::npos) {
        host = hostPort.substr(0, colonPos);
        port = std::stoi(hostPort.substr(colonPos + 1));
    } else {
        host = hostPort;
    }

    struct addrinfo hints{}, *res = nullptr;
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    std::string portStr = std::to_string(port);

    if (getaddrinfo(host.c_str(), portStr.c_str(), &hints, &res) != 0) {
        throw std::runtime_error("Bootstrap failed: DNS resolution error");
    }

    int sock = static_cast<int>(socket(res->ai_family, res->ai_socktype, res->ai_protocol));
    if (sock < 0) {
        freeaddrinfo(res);
        throw std::runtime_error("Bootstrap failed: socket creation error");
    }

#ifdef _WIN32
    DWORD tv = static_cast<DWORD>(timeoutSec * 1000);
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&tv), sizeof(tv));
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, reinterpret_cast<const char*>(&tv), sizeof(tv));
#else
    struct timeval tv;
    tv.tv_sec = timeoutSec;
    tv.tv_usec = 0;
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
#endif

    if (connect(sock, res->ai_addr, static_cast<int>(res->ai_addrlen)) != 0) {
        freeaddrinfo(res);
#ifdef _WIN32
        closesocket(sock);
#else
        close(sock);
#endif
        throw std::runtime_error("Bootstrap failed: connection error");
    }
    freeaddrinfo(res);

    std::ostringstream req;
    req << "POST " << path << " HTTP/1.1\r\n"
        << "Host: " << host << "\r\n"
        << "Content-Type: application/json\r\n"
        << "Content-Length: " << body.size() << "\r\n"
        << "Connection: close\r\n"
        << "\r\n"
        << body;

    std::string reqStr = req.str();
#ifdef _WIN32
    send(sock, reqStr.c_str(), static_cast<int>(reqStr.size()), 0);
#else
    send(sock, reqStr.c_str(), reqStr.size(), 0);
#endif

    std::string response;
    char buf[4096];
    int n;
#ifdef _WIN32
    while ((n = recv(sock, buf, sizeof(buf), 0)) > 0) {
        response.append(buf, static_cast<size_t>(n));
    }
    closesocket(sock);
#else
    while ((n = static_cast<int>(recv(sock, buf, sizeof(buf), 0))) > 0) {
        response.append(buf, static_cast<size_t>(n));
    }
    close(sock);
#endif

    auto bodyStart = response.find("\r\n\r\n");
    if (bodyStart == std::string::npos) {
        throw std::runtime_error("Bootstrap failed: invalid HTTP response");
    }

    if (response.find("HTTP/1.1 2") == std::string::npos &&
        response.find("HTTP/1.0 2") == std::string::npos) {
        throw std::runtime_error("Bootstrap failed: " + response.substr(bodyStart + 4));
    }

    return response.substr(bodyStart + 4);
}

inline BootstrapResult bootstrapProfile(
    const std::string& joinCode,
    const std::string& scope,
    const std::string& deviceName
) {
    auto cred = decodeCredential(joinCode);
    std::string relayUrl = cred["relay_url"].get<std::string>();
    while (!relayUrl.empty() && relayUrl.back() == '/') relayUrl.pop_back();

    nlohmann::json payload = {
        {"join_code", joinCode},
        {"scope", scope},
        {"device_name", deviceName}
    };

    std::string responseBody = httpPost(relayUrl + "/v1/bootstrap", payload.dump());
    auto data = nlohmann::json::parse(responseBody);
    std::string accessToken = data.value("access_token", "");
    if (accessToken.empty()) {
        throw std::runtime_error("Bootstrap response missing access_token.");
    }

    return {relayUrl, accessToken};
}

inline bool isLanCode(const std::string& code) {
    if (code.compare(0, LAN_TOKEN_PREFIX.size(), LAN_TOKEN_PREFIX) == 0)
        return true;
    for (size_t i = 0; i < LEGACY_LAN_COUNT; ++i) {
        std::string prefix(LEGACY_LAN_PREFIXES[i]);
        if (code.compare(0, prefix.size(), prefix) == 0) return true;
    }
    return false;
}

inline bool isRelayToken(const std::string& code) {
    return code.compare(0, TOKEN_PREFIX.size(), TOKEN_PREFIX) == 0 && !isLanCode(code);
}

inline std::string parseLanCode(const std::string& code) {
    auto r = decodeLanCode(code);
    return "http://" + r.host + ":" + std::to_string(r.port);
}

inline std::string httpToWs(const std::string& url) {
    if (url.compare(0, 8, "https://") == 0)
        return "wss://" + url.substr(8);
    if (url.compare(0, 7, "http://") == 0)
        return "ws://" + url.substr(7);
    return url;
}

struct ConnectionConfig {
    std::string mode;
    std::string baseUrl;
    std::string accessToken;

    std::string relayEdgeWsUrl() const {
        std::string base = baseUrl;
        while (!base.empty() && base.back() == '/') base.pop_back();
        return httpToWs(base) + "/ws/edge";
    }
};

inline ConnectionConfig resolveConnection(const std::string& code, const std::string& edgeName) {
    std::string relayUrl = getenvStr("YUMI_RELAY_URL");
    std::string accessToken = getenvStr("YUMI_ACCESS_TOKEN");
    if (!relayUrl.empty() && !accessToken.empty()) {
        while (!relayUrl.empty() && relayUrl.back() == '/') relayUrl.pop_back();
        return {"relay", relayUrl, accessToken};
    }

    if (code.compare(0, 5, "ws://") == 0 || code.compare(0, 6, "wss://") == 0) {
        return {"direct", code, ""};
    }

    if (isLanCode(code)) {
        std::string serverUrl = parseLanCode(code);
        while (!serverUrl.empty() && serverUrl.back() == '/') serverUrl.pop_back();
        std::string wsUrl = httpToWs(serverUrl) + "/ws/edge";
        return {"direct", wsUrl, ""};
    }

    if (isRelayToken(code)) {
        auto profile = bootstrapProfile(code, "edge", edgeName);
#ifdef _WIN32
        _putenv_s("YUMI_RELAY_URL", profile.relayUrl.c_str());
        _putenv_s("YUMI_ACCESS_TOKEN", profile.accessToken.c_str());
#else
        setenv("YUMI_RELAY_URL", profile.relayUrl.c_str(), 1);
        setenv("YUMI_ACCESS_TOKEN", profile.accessToken.c_str(), 1);
#endif
        return {"relay", profile.relayUrl, profile.accessToken};
    }

    if (code.compare(0, 7, "http://") == 0 || code.compare(0, 8, "https://") == 0) {
        std::string base = code;
        while (!base.empty() && base.back() == '/') base.pop_back();
        std::string wsUrl = httpToWs(base) + "/ws/edge";
        return {"direct", wsUrl, ""};
    }

    return {"direct", "ws://127.0.0.1:8000/ws/edge", ""};
}

inline std::string getHostname() {
    char buf[256];
#ifdef _WIN32
    DWORD size = sizeof(buf);
    if (GetComputerNameA(buf, &size)) return std::string(buf, size);
#else
    if (gethostname(buf, sizeof(buf)) == 0) return std::string(buf);
#endif
    return "unknown";
}

} // namespace detail

// ═══════════════════════════════════════════════════════════════════════════
//  YumiAgent
// ═══════════════════════════════════════════════════════════════════════════

class YumiAgent {
public:
#if defined(YUMI_SDK_IXWEBSOCKET_AVAILABLE)
    /**
     * Zero-config path: connection code only (LAN / relay / ws URL / empty + .env).
     * Uses **DefaultTransport** (IXWebSocket) internally.
     */
    explicit YumiAgent(std::string connectionCode)
        : YumiAgent(std::move(connectionCode), std::make_shared<DefaultTransport>()) {}

    /**
     * Default transport + explicit edge name (empty *edgeName* → same as single-arg ctor).
     */
    YumiAgent(std::string connectionCode, std::string edgeName)
        : YumiAgent(
              std::move(connectionCode),
              std::move(edgeName),
              "",
              std::make_shared<DefaultTransport>()) {}

    /**
     * Default transport + explicit edge name and .env path (C API / tooling).
     */
    YumiAgent(std::string connectionCode, std::string edgeName, std::string envPath)
        : YumiAgent(
              std::move(connectionCode),
              std::move(edgeName),
              std::move(envPath),
              std::make_shared<DefaultTransport>()) {}
#endif

    /**
     * Advanced path: inject **IYumiTransport** (UE5, corporate proxy, tests, …).
     */
    YumiAgent(std::string connectionCode, std::shared_ptr<IYumiTransport> customTransport)
        : transport_(std::move(customTransport)),
          connectionCode_(std::move(connectionCode))
    {
        if (!transport_) {
            throw std::invalid_argument("YumiAgent: customTransport must not be null");
        }
        initFromEnv("", nullptr);
    }

    /**
     * Full control: connection code, optional edge name, optional .env path, custom transport.
     * Pass empty *edgeName* to fall back to **EDGE_NAME** / hostname.
     */
    YumiAgent(
        std::string connectionCode,
        std::string edgeName,
        std::string envPath,
        std::shared_ptr<IYumiTransport> customTransport
    )
        : transport_(std::move(customTransport)),
          connectionCode_(std::move(connectionCode))
    {
        if (!transport_) {
            throw std::invalid_argument("YumiAgent: customTransport must not be null");
        }
        const std::string* edgePtr = edgeName.empty() ? nullptr : &edgeName;
        initFromEnv(envPath, edgePtr);
    }

    ~YumiAgent() { stop(); }

    YumiAgent(const YumiAgent&) = delete;
    YumiAgent& operator=(const YumiAgent&) = delete;

    void registerTool(RegisterOptions opts) {
        auto schema = buildToolSchema(
            opts.name, opts.description, opts.parameters,
            opts.requireConfirmation, opts.timeout, opts.alwaysInclude,
            opts.allowProactive, opts.proactiveContext,
            opts.proactiveContextArgs, opts.proactiveContextDescription
        );

        std::lock_guard<std::mutex> lock(toolsMutex_);
        tools_[opts.name] = {
            std::move(schema),
            std::move(opts.handler),
            opts.requireConfirmation
        };
    }

    void runInBackground() {
        if (tools_.empty()) {
            std::cout << "[Yumi] Warning: no tools registered." << std::endl;
        }

        if (bgThread_.joinable()) {
            stopRequested_ = true;
            if (transport_) transport_->stop();
            bgThread_.join();
        }

        stopRequested_ = false;
        bgThread_ = std::thread([this] { connectLoop(); });
    }

    void stop() {
        stopRequested_ = true;
        if (transport_) {
            transport_->stop();
        }
        if (bgThread_.joinable()) {
            bgThread_.join();
        }
    }

    bool isRunning() const { return !stopRequested_.load(); }

private:
    struct RegisteredTool {
        nlohmann::json schema;
        ToolHandler handler;
        bool requireConfirmation;
    };

    /// @param edgeNameFromCaller  If non-null and non-empty, overrides EDGE_NAME / hostname.
    void initFromEnv(const std::string& envPath, const std::string* edgeNameFromCaller) {
        std::string envFile;
        if (!envPath.empty()) {
            envFile = envPath;
        } else {
            std::string cwd;
#ifdef _WIN32
            char cwdBuf[MAX_PATH];
            if (_getcwd(cwdBuf, static_cast<int>(sizeof(cwdBuf)))) cwd = cwdBuf;
#else
            char cwdBuf[4096];
            if (getcwd(cwdBuf, sizeof(cwdBuf))) cwd = cwdBuf;
#endif
            std::string mtEnv = cwd + "/yumi_tools/.env";
            std::string rootEnv = cwd + "/.env";
            std::ifstream testMt(mtEnv);
            envFile = testMt.good() ? mtEnv : rootEnv;
        }

        detail::loadEnvFile(envFile);

        auto lastSlash = envFile.rfind('/');
#ifdef _WIN32
        auto lastBack = envFile.rfind('\\');
        if (lastBack != std::string::npos && (lastSlash == std::string::npos || lastBack > lastSlash))
            lastSlash = lastBack;
#endif
        policyBaseDir_ = (lastSlash != std::string::npos) ? envFile.substr(0, lastSlash) : ".";

        if (connectionCode_.empty()) {
            const char* envCode = std::getenv("YUMI_CONNECTION_CODE");
            if (!envCode) envCode = std::getenv("BRAIN_URL");
            connectionCode_ = envCode ? envCode : "";
        }

        if (edgeNameFromCaller && !edgeNameFromCaller->empty()) {
            edgeName_ = *edgeNameFromCaller;
        } else {
            const char* envName = std::getenv("EDGE_NAME");
            edgeName_ = envName ? envName : detail::getHostname();
        }
    }

    std::string confirmationPolicyPath() const {
        const char* override = std::getenv("YUMI_TOOL_CONFIRMATION_PATH");
        if (override && override[0] != '\0') return std::string(override);
        return policyBaseDir_ + "/.yumi_tool_confirmation.json";
    }

    nlohmann::json loadConfirmationPolicy() const {
        std::string path = confirmationPolicyPath();
        std::ifstream file(path);
        if (!file.is_open()) {
            return {
                {"always_allow", nlohmann::json::array()},
                {"force_confirm", nlohmann::json::array()}
            };
        }
        try {
            nlohmann::json raw;
            file >> raw;
            return {
                {"always_allow", raw.value("always_allow", nlohmann::json::array())},
                {"force_confirm", raw.value("force_confirm", nlohmann::json::array())}
            };
        } catch (...) {
            return {
                {"always_allow", nlohmann::json::array()},
                {"force_confirm", nlohmann::json::array()}
            };
        }
    }

    void saveConfirmationPolicy(const nlohmann::json& data) const {
        try {
            std::ofstream file(confirmationPolicyPath());
            if (file.is_open()) file << data.dump(2);
        } catch (...) {}
    }

    void connectLoop() {
        int reconnectDelay = 3;

        while (!stopRequested_) {
            detail::ConnectionConfig connection;
            try {
                connection = detail::resolveConnection(connectionCode_, edgeName_);
            } catch (const std::exception& e) {
                std::cerr << "[Yumi] Failed to resolve connection: " << e.what() << std::endl;
                return;
            }

            const std::string wsUrl = (connection.mode == "relay")
                ? connection.relayEdgeWsUrl()
                : connection.baseUrl;

            std::mutex sessionMutex;
            std::condition_variable sessionCv;
            bool sessionDone = false;

            transport_->stop();
            transport_->setUrl(wsUrl);

            transport_->setHandlers(
                [this, &connection]() {
                    nlohmann::json toolSchemas = nlohmann::json::array();
                    {
                        std::lock_guard<std::mutex> lock(toolsMutex_);
                        for (const auto& kv : tools_) {
                            nlohmann::json schema = kv.second.schema;
                            if (kv.second.requireConfirmation) {
                                schema["require_confirmation"] = true;
                            }
                            toolSchemas.push_back(std::move(schema));
                        }
                    }

                    nlohmann::json registerPayload = {
                        {"type", "register"},
                        {"edge_name", edgeName_},
                        {"tools", toolSchemas},
                        {"tool_confirmation_policy", loadConfirmationPolicy()}
                    };
                    if (!connection.accessToken.empty()) {
                        registerPayload["access_token"] = connection.accessToken;
                    }

                    transport_->sendText(registerPayload.dump());
                    std::cout << "[Yumi] Connected as [" << edgeName_ << "] with "
                              << tools_.size() << " tool(s)." << std::endl;
                },
                [this](std::string_view text) {
                    try {
                        auto msgJson = nlohmann::json::parse(text);
                        std::string msgType = msgJson.value("type", "");

                        if (msgType == "persist_tool_confirmation_policy") {
                            saveConfirmationPolicy({
                                {"always_allow", msgJson.value("always_allow", nlohmann::json::array())},
                                {"force_confirm", msgJson.value("force_confirm", nlohmann::json::array())}
                            });
                        } else if (msgType == "tool_call") {
                            std::string toolName = msgJson.value("name", "");
                            nlohmann::json arguments = msgJson.value("arguments", nlohmann::json::object());
                            std::string callId = msgJson.value("call_id", "unknown");

                            std::string result;
                            ToolHandler handler;
                            {
                                std::lock_guard<std::mutex> lock(toolsMutex_);
                                auto it = tools_.find(toolName);
                                if (it == tools_.end()) {
                                    result = "Error: Tool '" + toolName + "' is not registered on this edge.";
                                } else {
                                    handler = it->second.handler;
                                }
                            }
                            if (handler) {
                                try {
                                    ToolArguments args(arguments);
                                    result = handler(args);
                                } catch (const std::exception& e) {
                                    result = std::string("Error executing tool '") + toolName + "': " + e.what();
                                }
                            }

                            nlohmann::json response = {
                                {"type", "tool_result"},
                                {"call_id", callId},
                                {"result", result},
                                {"cancelled", false}
                            };
                            transport_->sendText(response.dump());
                        }
                    } catch (...) {}
                },
                [&sessionDone, &sessionCv, &sessionMutex]() {
                    std::lock_guard<std::mutex> lk(sessionMutex);
                    sessionDone = true;
                    sessionCv.notify_all();
                },
                [&sessionDone, &sessionCv, &sessionMutex](std::string) {
                    std::lock_guard<std::mutex> lk(sessionMutex);
                    sessionDone = true;
                    sessionCv.notify_all();
                }
            );

            transport_->start();

            {
                std::unique_lock<std::mutex> lk(sessionMutex);
                sessionCv.wait(lk, [&] {
                    return sessionDone || stopRequested_.load();
                });
            }

            transport_->stop();

            if (stopRequested_) break;

            std::random_device rd;
            std::mt19937 gen(rd());
            std::uniform_int_distribution<int> jitterMs(-500, 500);
            int totalMs = reconnectDelay * 1000 + jitterMs(gen);
            if (totalMs < 1000) totalMs = 1000;
            std::cout << "[Yumi] Connection lost. Reconnecting in " << (totalMs / 1000.0) << "s..." << std::endl;

            for (int elapsed = 0; elapsed < totalMs && !stopRequested_; elapsed += 100) {
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
            }
            reconnectDelay = std::min(reconnectDelay * 2, 30);
        }
    }

    std::shared_ptr<IYumiTransport> transport_;
    std::string connectionCode_;
    std::string edgeName_;
    std::string policyBaseDir_;

    std::map<std::string, RegisteredTool> tools_;
    std::mutex toolsMutex_;

    std::thread bgThread_;
    std::atomic<bool> stopRequested_{false};
};

} // namespace yumi
