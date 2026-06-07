#pragma once

#include "CoreMinimal.h"

namespace YumiConnection
{

struct FConnectionConfig
{
    FString Mode;         // "direct" or "relay"
    FString BaseUrl;
    FString AccessToken;  // empty for direct

    FString RelayEdgeWsUrl() const;
};

FString HttpToWs(const FString& Url);

/**
 * Resolve connection configuration from code, environment, or defaults.
 * For relay tokens, calls BootstrapProfile asynchronously.
 * @param OnResolved  Called on game thread with the resolved config.
 */
void ResolveConnection(
    const FString& Code,
    const FString& EdgeName,
    TFunction<void(TOptional<FConnectionConfig>)> OnResolved
);

/**
 * Synchronous resolution for non-relay codes (LAN, direct WS, HTTP, fallback).
 * Returns empty optional for relay tokens (use async version instead).
 */
TOptional<FConnectionConfig> ResolveConnectionSync(
    const FString& Code,
    const FString& EdgeName
);

} // namespace YumiConnection
