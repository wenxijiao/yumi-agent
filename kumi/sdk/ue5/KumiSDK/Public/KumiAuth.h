#pragma once

#include "CoreMinimal.h"

namespace KumiAuth
{

struct FLanCodeResult
{
    FString Host;
    int32 Port = 8000;
};

struct FBootstrapResult
{
    FString RelayUrl;
    FString AccessToken;
};

FString B64UrlDecode(const FString& Data);

FLanCodeResult DecodeLanCode(const FString& Token);

TSharedPtr<FJsonObject> DecodeCredential(const FString& Token);

bool IsLanCode(const FString& Code);

bool IsRelayToken(const FString& Code);

FString ParseLanCode(const FString& Code);

/**
 * POST to relay /v1/bootstrap.
 * Calls OnComplete on the game thread with the result or empty on failure.
 */
void BootstrapProfile(
    const FString& JoinCode,
    const FString& Scope,
    const FString& DeviceName,
    TFunction<void(TOptional<FBootstrapResult>)> OnComplete
);

} // namespace KumiAuth
