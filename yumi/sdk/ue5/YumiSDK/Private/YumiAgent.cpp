#include "YumiAgent.h"
#include "YumiAuth.h"
#include "YumiConnection.h"

#include "WebSocketsModule.h"
#include "IWebSocket.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonWriter.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "HAL/PlatformProcess.h"
#include "TimerManager.h"
#include "Engine/World.h"

static const FString LogPrefix = TEXT("[Yumi]");
static const FString ConfirmationFilename = TEXT(".yumi_tool_confirmation.json");

// ── FYumiToolArguments ──

FString FYumiToolArguments::GetString(const FString& Key, const FString& Default) const
{
    if (!Raw.IsValid()) return Default;
    FString Value;
    return Raw->TryGetStringField(Key, Value) ? Value : Default;
}

int32 FYumiToolArguments::GetInt(const FString& Key, int32 Default) const
{
    if (!Raw.IsValid()) return Default;
    int32 Value;
    return Raw->TryGetNumberField(Key, Value) ? Value : Default;
}

double FYumiToolArguments::GetNumber(const FString& Key, double Default) const
{
    if (!Raw.IsValid()) return Default;
    double Value;
    return Raw->TryGetNumberField(Key, Value) ? Value : Default;
}

bool FYumiToolArguments::GetBool(const FString& Key, bool Default) const
{
    if (!Raw.IsValid()) return Default;
    bool Value;
    return Raw->TryGetBoolField(Key, Value) ? Value : Default;
}

// ── .env parser ──

void FYumiAgent::LoadEnvFile(const FString& Path)
{
    FString Content;
    if (!FFileHelper::LoadFileToString(Content, *Path))
        return;

    TArray<FString> Lines;
    Content.ParseIntoArrayLines(Lines);

    for (const FString& RawLine : Lines)
    {
        FString Line = RawLine.TrimStartAndEnd();
        if (Line.IsEmpty() || Line.StartsWith(TEXT("#")))
            continue;

        int32 EqIdx;
        if (!Line.FindChar(TEXT('='), EqIdx))
            continue;

        FString Key = Line.Left(EqIdx).TrimStartAndEnd();
        FString Value = Line.Mid(EqIdx + 1).TrimStartAndEnd();

        if (Value.Len() >= 2)
        {
            if ((Value.StartsWith(TEXT("\"")) && Value.EndsWith(TEXT("\""))) ||
                (Value.StartsWith(TEXT("'")) && Value.EndsWith(TEXT("'"))))
            {
                Value = Value.Mid(1, Value.Len() - 2);
            }
        }

        FString Existing = FPlatformMisc::GetEnvironmentVariable(*Key);
        if (Existing.IsEmpty())
        {
            FPlatformMisc::SetEnvironmentVar(*Key, *Value);
        }
    }
}

// ── Constructor ──

FYumiAgent::FYumiAgent(
    const FString& InConnectionCode,
    const FString& InEdgeName,
    const FString& InEnvPath
)
{
    FModuleManager::Get().LoadModuleChecked(TEXT("WebSockets"));

    FString EnvFile;
    if (!InEnvPath.IsEmpty())
    {
        EnvFile = InEnvPath;
    }
    else
    {
        FString ProjectDir = FPaths::ProjectDir();
        FString MtEnv = FPaths::Combine(ProjectDir, TEXT("yumi_tools"), TEXT(".env"));
        FString RootEnv = FPaths::Combine(ProjectDir, TEXT(".env"));
        EnvFile = FPaths::FileExists(MtEnv) ? MtEnv : RootEnv;
    }

    LoadEnvFile(EnvFile);
    PolicyBaseDir = FPaths::GetPath(FPaths::ConvertRelativePathToFull(EnvFile));

    if (!InConnectionCode.IsEmpty())
    {
        ConnectionCode = InConnectionCode;
    }
    else
    {
        ConnectionCode = FPlatformMisc::GetEnvironmentVariable(TEXT("YUMI_CONNECTION_CODE"));
        if (ConnectionCode.IsEmpty())
        {
            ConnectionCode = FPlatformMisc::GetEnvironmentVariable(TEXT("BRAIN_URL"));
        }
    }

    if (!InEdgeName.IsEmpty())
    {
        EdgeName = InEdgeName;
    }
    else
    {
        EdgeName = FPlatformMisc::GetEnvironmentVariable(TEXT("EDGE_NAME"));
        if (EdgeName.IsEmpty())
        {
            EdgeName = FPlatformProcess::ComputerName();
        }
    }
}

FYumiAgent::~FYumiAgent()
{
    Stop();
}

// ── Tool schema ──

TSharedPtr<FJsonObject> FYumiAgent::BuildToolSchema(const FYumiRegisterOptions& Opts) const
{
    TSharedPtr<FJsonObject> Properties = MakeShareable(new FJsonObject());
    TArray<TSharedPtr<FJsonValue>> RequiredArr;

    for (const auto& Param : Opts.Parameters)
    {
        TSharedPtr<FJsonObject> PropObj = MakeShareable(new FJsonObject());
        PropObj->SetStringField(TEXT("type"), Param.Type);
        PropObj->SetStringField(TEXT("description"), Param.Description);
        Properties->SetObjectField(Param.Name, PropObj);

        if (Param.bRequired)
        {
            RequiredArr.Add(MakeShareable(new FJsonValueString(Param.Name)));
        }
    }

    TSharedPtr<FJsonObject> Params = MakeShareable(new FJsonObject());
    Params->SetStringField(TEXT("type"), TEXT("object"));
    Params->SetObjectField(TEXT("properties"), Properties);
    Params->SetArrayField(TEXT("required"), RequiredArr);

    TSharedPtr<FJsonObject> Func = MakeShareable(new FJsonObject());
    Func->SetStringField(TEXT("name"), Opts.Name);
    Func->SetStringField(TEXT("description"), Opts.Description);
    Func->SetObjectField(TEXT("parameters"), Params);

    TSharedPtr<FJsonObject> Schema = MakeShareable(new FJsonObject());
    Schema->SetStringField(TEXT("type"), TEXT("function"));
    Schema->SetObjectField(TEXT("function"), Func);

    if (Opts.Timeout > 0)
    {
        Schema->SetNumberField(TEXT("timeout"), Opts.Timeout);
    }
    if (Opts.bRequireConfirmation)
    {
        Schema->SetBoolField(TEXT("require_confirmation"), true);
    }
    if (Opts.bAlwaysInclude)
    {
        Schema->SetBoolField(TEXT("always_include"), true);
    }
    if (Opts.bAllowProactive)
    {
        Schema->SetBoolField(TEXT("allow_proactive"), true);
    }
    if (Opts.bProactiveContext)
    {
        Schema->SetBoolField(TEXT("proactive_context"), true);
    }
    if (Opts.ProactiveContextArgs.IsValid())
    {
        Schema->SetObjectField(TEXT("proactive_context_args"), Opts.ProactiveContextArgs);
    }
    if (!Opts.ProactiveContextDescription.IsEmpty())
    {
        Schema->SetStringField(TEXT("proactive_context_description"), Opts.ProactiveContextDescription);
    }

    return Schema;
}

// ── Public API ──

void FYumiAgent::RegisterTool(FYumiRegisterOptions Opts)
{
    // Map the Mode API onto the existing wire flags (one mode per tool).
    if (Opts.Mode == TEXT("pinned"))
    {
        Opts.bAlwaysInclude = true;
    }
    else if (Opts.Mode == TEXT("autorun"))
    {
        Opts.bProactiveContext = true;
        if (Opts.ContextArgs.IsValid())
        {
            Opts.ProactiveContextArgs = Opts.ContextArgs;
        }
        if (!Opts.ContextLabel.IsEmpty())
        {
            Opts.ProactiveContextDescription = Opts.ContextLabel;
        }
    }
    else if (Opts.Mode != TEXT("dynamic"))
    {
        UE_LOG(LogTemp, Error,
            TEXT("%s RegisterTool('%s'): invalid mode '%s' (expected 'dynamic', 'pinned', or 'autorun'); tool not registered."),
            *LogPrefix, *Opts.Name, *Opts.Mode);
        return;
    }

    TSharedPtr<FJsonObject> Schema = BuildToolSchema(Opts);
    FRegisteredTool Tool;
    Tool.Schema = Schema;
    Tool.Handler = MoveTemp(Opts.Handler);
    Tool.bRequireConfirmation = Opts.bRequireConfirmation;
    Tools.Add(Opts.Name, MoveTemp(Tool));
}

void FYumiAgent::RunInBackground()
{
    if (Tools.Num() == 0)
    {
        UE_LOG(LogTemp, Warning, TEXT("%s Warning: no tools registered."), *LogPrefix);
    }

    bStopRequested = false;
    bRunning = true;
    ReconnectDelay = 3;

    YumiConnection::ResolveConnection(ConnectionCode, EdgeName,
        [this](TOptional<YumiConnection::FConnectionConfig> Config)
        {
            if (!Config.IsSet())
            {
                UE_LOG(LogTemp, Error, TEXT("%s Failed to resolve connection."), *LogPrefix);
                bRunning = false;
                return;
            }

            FString WsUrl = (Config->Mode == TEXT("relay"))
                ? Config->RelayEdgeWsUrl()
                : Config->BaseUrl;

            // Store connection info for reconnects
            ConnectionCode = WsUrl;
            if (!Config->AccessToken.IsEmpty())
            {
                FPlatformMisc::SetEnvironmentVar(TEXT("YUMI_ACCESS_TOKEN"), *Config->AccessToken);
            }

            ConnectToServer();
        }
    );
}

void FYumiAgent::Stop()
{
    bStopRequested = true;
    bRunning = false;

    if (WebSocket)
    {
        WebSocket->Close();
        WebSocket = nullptr;
    }
}

// ── Confirmation policy ──

FString FYumiAgent::ConfirmationPolicyPath() const
{
    FString Override = FPlatformMisc::GetEnvironmentVariable(TEXT("YUMI_TOOL_CONFIRMATION_PATH"));
    if (!Override.IsEmpty())
        return Override;
    return FPaths::Combine(PolicyBaseDir, ConfirmationFilename);
}

TSharedPtr<FJsonObject> FYumiAgent::LoadConfirmationPolicy() const
{
    TSharedPtr<FJsonObject> Result = MakeShareable(new FJsonObject());
    Result->SetArrayField(TEXT("always_allow"), TArray<TSharedPtr<FJsonValue>>());
    Result->SetArrayField(TEXT("force_confirm"), TArray<TSharedPtr<FJsonValue>>());

    FString Path = ConfirmationPolicyPath();
    FString Content;
    if (!FFileHelper::LoadFileToString(Content, *Path))
        return Result;

    TSharedPtr<FJsonObject> Parsed;
    TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Content);
    if (FJsonSerializer::Deserialize(Reader, Parsed) && Parsed.IsValid())
    {
        if (Parsed->HasField(TEXT("always_allow")))
            Result->SetArrayField(TEXT("always_allow"), Parsed->GetArrayField(TEXT("always_allow")));
        if (Parsed->HasField(TEXT("force_confirm")))
            Result->SetArrayField(TEXT("force_confirm"), Parsed->GetArrayField(TEXT("force_confirm")));
    }

    return Result;
}

void FYumiAgent::SaveConfirmationPolicy(TSharedPtr<FJsonObject> Data) const
{
    FString Path = ConfirmationPolicyPath();
    FString Output;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(Data.ToSharedRef(), Writer);
    FFileHelper::SaveStringToFile(Output, *Path);
}

// ── WebSocket ──

void FYumiAgent::ConnectToServer()
{
    if (bStopRequested) return;

    FString WsUrl = ConnectionCode;
    WebSocket = FWebSocketsModule::Get().CreateWebSocket(WsUrl, TEXT("ws"));

    WebSocket->OnConnected().AddLambda([this]() { OnConnected(); });
    WebSocket->OnMessage().AddLambda([this](const FString& Msg) { OnMessage(Msg); });
    WebSocket->OnClosed().AddLambda([this](int32 Code, const FString& Reason, bool bClean) { OnClosed(Code, Reason, bClean); });
    WebSocket->OnConnectionError().AddLambda([this](const FString& Err) { OnError(Err); });

    WebSocket->Connect();
}

void FYumiAgent::OnConnected()
{
    ReconnectDelay = 3;

    TArray<TSharedPtr<FJsonValue>> ToolSchemas;
    for (const auto& Pair : Tools)
    {
        TSharedPtr<FJsonObject> Schema = MakeShareable(new FJsonObject());
        // Deep copy
        for (const auto& Field : Pair.Value.Schema->Values)
        {
            Schema->SetField(Field.Key, Field.Value);
        }
        if (Pair.Value.bRequireConfirmation)
        {
            Schema->SetBoolField(TEXT("require_confirmation"), true);
        }
        ToolSchemas.Add(MakeShareable(new FJsonValueObject(Schema)));
    }

    TSharedPtr<FJsonObject> Payload = MakeShareable(new FJsonObject());
    Payload->SetStringField(TEXT("type"), TEXT("register"));
    Payload->SetStringField(TEXT("edge_name"), EdgeName);
    Payload->SetArrayField(TEXT("tools"), ToolSchemas);
    Payload->SetObjectField(TEXT("tool_confirmation_policy"), LoadConfirmationPolicy());

    FString AccessToken = FPlatformMisc::GetEnvironmentVariable(TEXT("YUMI_ACCESS_TOKEN"));
    if (!AccessToken.IsEmpty())
    {
        Payload->SetStringField(TEXT("access_token"), AccessToken);
    }

    FString PayloadStr;
    TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&PayloadStr);
    FJsonSerializer::Serialize(Payload.ToSharedRef(), Writer);

    WebSocket->Send(PayloadStr);

    UE_LOG(LogTemp, Log, TEXT("%s Connected as [%s] with %d tool(s)."),
        *LogPrefix, *EdgeName, Tools.Num());
}

void FYumiAgent::OnMessage(const FString& Message)
{
    TSharedPtr<FJsonObject> Msg;
    TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Message);
    if (!FJsonSerializer::Deserialize(Reader, Msg) || !Msg.IsValid())
        return;

    FString MsgType = Msg->GetStringField(TEXT("type"));

    if (MsgType == TEXT("persist_tool_confirmation_policy"))
    {
        TSharedPtr<FJsonObject> Policy = MakeShareable(new FJsonObject());
        Policy->SetArrayField(TEXT("always_allow"), Msg->GetArrayField(TEXT("always_allow")));
        Policy->SetArrayField(TEXT("force_confirm"), Msg->GetArrayField(TEXT("force_confirm")));
        SaveConfirmationPolicy(Policy);
    }
    else if (MsgType == TEXT("tool_call"))
    {
        HandleToolCall(Msg);
    }
    else if (MsgType == TEXT("cancel"))
    {
        // Best-effort: UE5 tool handlers run synchronously on receive
    }
    else if (MsgType == TEXT("register_warning"))
    {
        int32 Dropped = Msg->HasField(TEXT("skipped_tools")) ? Msg->GetArrayField(TEXT("skipped_tools")).Num() : 0;
        UE_LOG(LogTemp, Warning, TEXT("%s Server did not mount %d tool(s)."), *LogPrefix, Dropped);
    }
    else if (MsgType == TEXT("register_rejected"))
    {
        // Refused (edge_name in use). Stop — don't reconnect to be rejected again.
        FString Reason = Msg->HasField(TEXT("reason")) ? Msg->GetStringField(TEXT("reason")) : TEXT("edge_name already in use");
        UE_LOG(LogTemp, Error, TEXT("%s Edge registration rejected by server: %s"), *LogPrefix, *Reason);
        bStopRequested = true;
        bRunning = false;
    }
}

void FYumiAgent::HandleToolCall(TSharedPtr<FJsonObject> Msg)
{
    FString ToolName = Msg->GetStringField(TEXT("name"));
    TSharedPtr<FJsonObject> Arguments = Msg->GetObjectField(TEXT("arguments"));
    FString CallId = Msg->GetStringField(TEXT("call_id"));
    if (CallId.IsEmpty()) CallId = TEXT("unknown");

    FString Result;
    bool bCancelled = false;

    FRegisteredTool* Tool = Tools.Find(ToolName);
    if (!Tool)
    {
        Result = FString::Printf(TEXT("Error: Tool '%s' is not registered on this edge."), *ToolName);
    }
    else
    {
        FYumiToolArguments Args(Arguments);
        Result = Tool->Handler.Execute(Args);
    }

    TSharedPtr<FJsonObject> Response = MakeShareable(new FJsonObject());
    Response->SetStringField(TEXT("type"), TEXT("tool_result"));
    Response->SetStringField(TEXT("call_id"), CallId);
    Response->SetStringField(TEXT("result"), Result);
    Response->SetBoolField(TEXT("cancelled"), bCancelled);

    FString ResponseStr;
    TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&ResponseStr);
    FJsonSerializer::Serialize(Response.ToSharedRef(), Writer);

    if (WebSocket)
    {
        WebSocket->Send(ResponseStr);
    }
}

void FYumiAgent::OnClosed(int32 StatusCode, const FString& Reason, bool bWasClean)
{
    WebSocket = nullptr;
    if (!bStopRequested)
    {
        ScheduleReconnect();
    }
}

void FYumiAgent::OnError(const FString& Error)
{
    UE_LOG(LogTemp, Warning, TEXT("%s Connection error: %s"), *LogPrefix, *Error);
    WebSocket = nullptr;
    if (!bStopRequested)
    {
        ScheduleReconnect();
    }
}

void FYumiAgent::ScheduleReconnect()
{
    UE_LOG(LogTemp, Log, TEXT("%s Connection lost. Reconnecting in %ds..."),
        *LogPrefix, ReconnectDelay);

    FTimerDelegate TimerDel;
    TimerDel.BindLambda([this]() { ConnectToServer(); });

    if (GEngine && GEngine->GetWorld())
    {
        GEngine->GetWorld()->GetTimerManager().SetTimer(
            ReconnectTimerHandle, TimerDel, static_cast<float>(ReconnectDelay), false);
    }
    else
    {
        // Fallback: use async task with delay
        float DelaySec = static_cast<float>(ReconnectDelay);
        FTSTicker::GetCoreTicker().AddTicker(
            FTickerDelegate::CreateLambda([this](float) -> bool {
                ConnectToServer();
                return false;
            }),
            DelaySec
        );
    }

    ReconnectDelay = FMath::Min(ReconnectDelay * 2, 30);
}
