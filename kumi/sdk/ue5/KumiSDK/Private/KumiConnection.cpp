#include "KumiConnection.h"
#include "KumiAuth.h"
#include "Misc/CommandLine.h"

namespace KumiConnection
{

FString HttpToWs(const FString& Url)
{
    if (Url.StartsWith(TEXT("https://")))
        return TEXT("wss://") + Url.Mid(8);
    if (Url.StartsWith(TEXT("http://")))
        return TEXT("ws://") + Url.Mid(7);
    return Url;
}

FString FConnectionConfig::RelayEdgeWsUrl() const
{
    FString Base = BaseUrl;
    while (Base.EndsWith(TEXT("/")))
    {
        Base.RemoveAt(Base.Len() - 1);
    }
    return HttpToWs(Base) + TEXT("/ws/edge");
}

static FString GetEnvVar(const FString& Name)
{
    return FPlatformMisc::GetEnvironmentVariable(*Name);
}

TOptional<FConnectionConfig> ResolveConnectionSync(
    const FString& Code,
    const FString& EdgeName
)
{
    FString RelayUrl = GetEnvVar(TEXT("KUMI_RELAY_URL"));
    FString AccessToken = GetEnvVar(TEXT("KUMI_ACCESS_TOKEN"));
    if (!RelayUrl.IsEmpty() && !AccessToken.IsEmpty())
    {
        while (RelayUrl.EndsWith(TEXT("/")))
            RelayUrl.RemoveAt(RelayUrl.Len() - 1);
        FConnectionConfig Config;
        Config.Mode = TEXT("relay");
        Config.BaseUrl = RelayUrl;
        Config.AccessToken = AccessToken;
        return Config;
    }

    if (Code.StartsWith(TEXT("ws://")) || Code.StartsWith(TEXT("wss://")))
    {
        FConnectionConfig Config;
        Config.Mode = TEXT("direct");
        Config.BaseUrl = Code;
        return Config;
    }

    if (KumiAuth::IsLanCode(Code))
    {
        FString ServerUrl = KumiAuth::ParseLanCode(Code);
        FString Base = ServerUrl;
        while (Base.EndsWith(TEXT("/")))
            Base.RemoveAt(Base.Len() - 1);
        FConnectionConfig Config;
        Config.Mode = TEXT("direct");
        Config.BaseUrl = HttpToWs(Base) + TEXT("/ws/edge");
        return Config;
    }

    if (KumiAuth::IsRelayToken(Code))
    {
        // Relay requires async bootstrap
        return {};
    }

    if (Code.StartsWith(TEXT("http://")) || Code.StartsWith(TEXT("https://")))
    {
        FString Base = Code;
        while (Base.EndsWith(TEXT("/")))
            Base.RemoveAt(Base.Len() - 1);
        FConnectionConfig Config;
        Config.Mode = TEXT("direct");
        Config.BaseUrl = HttpToWs(Base) + TEXT("/ws/edge");
        return Config;
    }

    FConnectionConfig Config;
    Config.Mode = TEXT("direct");
    Config.BaseUrl = TEXT("ws://127.0.0.1:8000/ws/edge");
    return Config;
}

void ResolveConnection(
    const FString& Code,
    const FString& EdgeName,
    TFunction<void(TOptional<FConnectionConfig>)> OnResolved
)
{
    // Try synchronous first (covers everything except relay tokens)
    TOptional<FConnectionConfig> SyncResult = ResolveConnectionSync(Code, EdgeName);
    if (SyncResult.IsSet())
    {
        OnResolved(SyncResult);
        return;
    }

    // Must be a relay token — bootstrap asynchronously
    if (KumiAuth::IsRelayToken(Code))
    {
        KumiAuth::BootstrapProfile(Code, TEXT("edge"), EdgeName,
            [OnResolved](TOptional<KumiAuth::FBootstrapResult> BootstrapResult)
            {
                if (!BootstrapResult.IsSet())
                {
                    OnResolved({});
                    return;
                }

                FConnectionConfig Config;
                Config.Mode = TEXT("relay");
                Config.BaseUrl = BootstrapResult->RelayUrl;
                Config.AccessToken = BootstrapResult->AccessToken;

                FPlatformMisc::SetEnvironmentVar(TEXT("KUMI_RELAY_URL"), *BootstrapResult->RelayUrl);
                FPlatformMisc::SetEnvironmentVar(TEXT("KUMI_ACCESS_TOKEN"), *BootstrapResult->AccessToken);

                OnResolved(Config);
            }
        );
        return;
    }

    // Fallback
    FConnectionConfig Config;
    Config.Mode = TEXT("direct");
    Config.BaseUrl = TEXT("ws://127.0.0.1:8000/ws/edge");
    OnResolved(Config);
}

} // namespace KumiConnection
