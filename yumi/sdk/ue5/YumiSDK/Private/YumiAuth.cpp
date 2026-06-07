#include "YumiAuth.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonReader.h"
#include "Misc/Base64.h"
#include "HttpModule.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"
#include "Misc/DateTime.h"

namespace YumiAuth
{

static const FString TokenPrefix = TEXT("yumi_");
static const FString LanTokenPrefix = TEXT("yumi-lan_");
static const FString LegacyLanPrefixes[] = { TEXT("ml1_"), TEXT("yumi_lan_") };

FString B64UrlDecode(const FString& Data)
{
    FString Input = Data;
    Input.ReplaceInline(TEXT("-"), TEXT("+"));
    Input.ReplaceInline(TEXT("_"), TEXT("/"));
    while (Input.Len() % 4 != 0)
    {
        Input += TEXT("=");
    }

    TArray<uint8> Decoded;
    FBase64::Decode(Input, Decoded);
    
    FUTF8ToTCHAR Converter(reinterpret_cast<const ANSICHAR*>(Decoded.GetData()), Decoded.Num());
    return FString(Converter.Length(), Converter.Get());
}

FLanCodeResult DecodeLanCode(const FString& Token)
{
    FString Encoded;

    if (Token.StartsWith(LanTokenPrefix))
    {
        Encoded = Token.Mid(LanTokenPrefix.Len());
    }
    else
    {
        bool bMatched = false;
        for (const auto& Prefix : LegacyLanPrefixes)
        {
            if (Token.StartsWith(Prefix))
            {
                Encoded = Token.Mid(Prefix.Len());
                bMatched = true;
                break;
            }
        }
        if (!bMatched)
        {
            UE_LOG(LogTemp, Error, TEXT("[Yumi] Invalid LAN code prefix."));
            return {};
        }
    }

    FString JsonStr = B64UrlDecode(Encoded);
    TSharedPtr<FJsonObject> JsonObj;
    TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonStr);
    if (!FJsonSerializer::Deserialize(Reader, JsonObj) || !JsonObj.IsValid())
    {
        UE_LOG(LogTemp, Error, TEXT("[Yumi] Failed to parse LAN code JSON."));
        return {};
    }

    FLanCodeResult Result;

    if (JsonObj->HasField(TEXT("h")))
    {
        Result.Host = JsonObj->GetStringField(TEXT("h"));
        Result.Port = JsonObj->HasField(TEXT("p")) ? static_cast<int32>(JsonObj->GetNumberField(TEXT("p"))) : 8000;
    }
    else if (JsonObj->HasField(TEXT("base_url")))
    {
        FString BaseUrl = JsonObj->GetStringField(TEXT("base_url"));
        // Simple URL parse
        FString HostPort = BaseUrl;
        int32 SchemeIdx;
        if (HostPort.FindChar(TEXT('/'), SchemeIdx))
        {
            int32 DoubleSlash = HostPort.Find(TEXT("//"));
            if (DoubleSlash != INDEX_NONE)
            {
                HostPort = HostPort.Mid(DoubleSlash + 2);
            }
        }
        int32 SlashIdx;
        if (HostPort.FindChar(TEXT('/'), SlashIdx))
        {
            HostPort = HostPort.Left(SlashIdx);
        }
        int32 ColonIdx;
        if (HostPort.FindLastChar(TEXT(':'), ColonIdx))
        {
            Result.Host = HostPort.Left(ColonIdx);
            Result.Port = FCString::Atoi(*HostPort.Mid(ColonIdx + 1));
        }
        else
        {
            Result.Host = HostPort;
            Result.Port = 8000;
        }
    }
    else
    {
        UE_LOG(LogTemp, Error, TEXT("[Yumi] LAN code missing host."));
        return {};
    }

    if (JsonObj->HasField(TEXT("x")))
    {
        int64 Expiry = static_cast<int64>(JsonObj->GetNumberField(TEXT("x")));
        if (Expiry != 0)
        {
            int64 Now = FDateTime::UtcNow().ToUnixTimestamp();
            if (Expiry < Now)
            {
                UE_LOG(LogTemp, Error, TEXT("[Yumi] LAN code has expired."));
                return {};
            }
        }
    }

    return Result;
}

TSharedPtr<FJsonObject> DecodeCredential(const FString& Token)
{
    if (!Token.StartsWith(TokenPrefix))
    {
        UE_LOG(LogTemp, Error, TEXT("[Yumi] Invalid credential prefix."));
        return nullptr;
    }

    FString JsonStr = B64UrlDecode(Token.Mid(TokenPrefix.Len()));
    TSharedPtr<FJsonObject> JsonObj;
    TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonStr);
    if (!FJsonSerializer::Deserialize(Reader, JsonObj))
    {
        return nullptr;
    }
    return JsonObj;
}

bool IsLanCode(const FString& Code)
{
    if (Code.StartsWith(LanTokenPrefix)) return true;
    for (const auto& Prefix : LegacyLanPrefixes)
    {
        if (Code.StartsWith(Prefix)) return true;
    }
    return false;
}

bool IsRelayToken(const FString& Code)
{
    return Code.StartsWith(TokenPrefix) && !IsLanCode(Code);
}

FString ParseLanCode(const FString& Code)
{
    FLanCodeResult Result = DecodeLanCode(Code);
    return FString::Printf(TEXT("http://%s:%d"), *Result.Host, Result.Port);
}

void BootstrapProfile(
    const FString& JoinCode,
    const FString& Scope,
    const FString& DeviceName,
    TFunction<void(TOptional<FBootstrapResult>)> OnComplete
)
{
    TSharedPtr<FJsonObject> Cred = DecodeCredential(JoinCode);
    if (!Cred.IsValid() || !Cred->HasField(TEXT("relay_url")))
    {
        OnComplete({});
        return;
    }

    FString RelayUrl = Cred->GetStringField(TEXT("relay_url"));
    while (RelayUrl.EndsWith(TEXT("/")))
    {
        RelayUrl.RemoveAt(RelayUrl.Len() - 1);
    }

    TSharedPtr<FJsonObject> Payload = MakeShareable(new FJsonObject());
    Payload->SetStringField(TEXT("join_code"), JoinCode);
    Payload->SetStringField(TEXT("scope"), Scope);
    Payload->SetStringField(TEXT("device_name"), DeviceName.TrimStartAndEnd());

    FString PayloadStr;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&PayloadStr);
    FJsonSerializer::Serialize(Payload.ToSharedRef(), Writer);

    auto Request = FHttpModule::Get().CreateRequest();
    Request->SetURL(RelayUrl + TEXT("/v1/bootstrap"));
    Request->SetVerb(TEXT("POST"));
    Request->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
    Request->SetContentAsString(PayloadStr);

    FString CapturedRelayUrl = RelayUrl;
    Request->OnProcessRequestComplete().BindLambda(
        [CapturedRelayUrl, OnComplete](FHttpRequestPtr, FHttpResponsePtr Response, bool bSuccess)
        {
            if (!bSuccess || !Response.IsValid() || Response->GetResponseCode() >= 400)
            {
                UE_LOG(LogTemp, Error, TEXT("[Yumi] Bootstrap failed."));
                OnComplete({});
                return;
            }

            TSharedPtr<FJsonObject> JsonObj;
            TSharedRef<TJsonReader<>> JsonReader = TJsonReaderFactory<>::Create(Response->GetContentAsString());
            if (!FJsonSerializer::Deserialize(JsonReader, JsonObj) || !JsonObj.IsValid())
            {
                OnComplete({});
                return;
            }

            FString AccessToken = JsonObj->GetStringField(TEXT("access_token"));
            if (AccessToken.IsEmpty())
            {
                OnComplete({});
                return;
            }

            FBootstrapResult Result;
            Result.RelayUrl = CapturedRelayUrl;
            Result.AccessToken = AccessToken;
            OnComplete(Result);
        }
    );
    Request->ProcessRequest();
}

} // namespace YumiAuth
