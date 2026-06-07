#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

/**
 * Tool parameter descriptor.
 */
struct FKumiToolParam
{
    FString Name;
    FString Type;         // "string", "integer", "number", "boolean", "array", "object"
    FString Description;
    bool bRequired = true;
};

/**
 * Type-safe wrapper for tool arguments received from the server.
 */
class FKumiToolArguments
{
public:
    explicit FKumiToolArguments(TSharedPtr<FJsonObject> InRaw) : Raw(MoveTemp(InRaw)) {}

    FString GetString(const FString& Key, const FString& Default = TEXT("")) const;
    int32 GetInt(const FString& Key, int32 Default = 0) const;
    double GetNumber(const FString& Key, double Default = 0.0) const;
    bool GetBool(const FString& Key, bool Default = false) const;
    TSharedPtr<FJsonObject> GetRawJson() const { return Raw; }

private:
    TSharedPtr<FJsonObject> Raw;
};

DECLARE_DELEGATE_RetVal_OneParam(FString, FKumiToolHandler, const FKumiToolArguments&);

/**
 * Tool registration options.
 */
struct FKumiRegisterOptions
{
    FString Name;
    FString Description;
    TArray<FKumiToolParam> Parameters;
    FKumiToolHandler Handler;
    int32 Timeout = 0;
    bool bRequireConfirmation = false;
    bool bAlwaysInclude = false;
    bool bAllowProactive = false;
    bool bProactiveContext = false;
    TSharedPtr<FJsonObject> ProactiveContextArgs;
    FString ProactiveContextDescription;
};

/**
 * Embeddable Kumi edge client for Unreal Engine 5.
 *
 * Usage:
 * @code
 * FKumiAgent Agent(TEXT("kumi-lan_..."), TEXT("My UE5 Game"));
 *
 * FKumiRegisterOptions Opts;
 * Opts.Name = TEXT("jump");
 * Opts.Description = TEXT("Make the character jump");
 * Opts.Handler.BindLambda([](const FKumiToolArguments& Args) -> FString {
 *     return TEXT("Jumped!");
 * });
 * Agent.RegisterTool(MoveTemp(Opts));
 *
 * Agent.RunInBackground();
 * @endcode
 *
 * Call Stop() or let the destructor handle cleanup.
 */
class KUMISDK_API FKumiAgent
{
public:
    FKumiAgent(
        const FString& ConnectionCode = TEXT(""),
        const FString& EdgeName = TEXT(""),
        const FString& EnvPath = TEXT("")
    );

    ~FKumiAgent();

    FKumiAgent(const FKumiAgent&) = delete;
    FKumiAgent& operator=(const FKumiAgent&) = delete;

    void RegisterTool(FKumiRegisterOptions Opts);

    void RunInBackground();

    void Stop();

    bool IsRunning() const { return bRunning; }

private:
    struct FRegisteredTool
    {
        TSharedPtr<FJsonObject> Schema;
        FKumiToolHandler Handler;
        bool bRequireConfirmation;
    };

    FString ConnectionCode;
    FString EdgeName;
    FString PolicyBaseDir;

    TMap<FString, FRegisteredTool> Tools;
    bool bRunning = false;
    bool bStopRequested = false;

    class IWebSocket* WebSocket = nullptr;
    FTimerHandle ReconnectTimerHandle;
    int32 ReconnectDelay = 3;

    // Confirmation policy
    FString ConfirmationPolicyPath() const;
    TSharedPtr<FJsonObject> LoadConfirmationPolicy() const;
    void SaveConfirmationPolicy(TSharedPtr<FJsonObject> Data) const;

    // Internal
    void ConnectToServer();
    void OnConnected();
    void OnMessage(const FString& Message);
    void OnClosed(int32 StatusCode, const FString& Reason, bool bWasClean);
    void OnError(const FString& Error);
    void HandleToolCall(TSharedPtr<FJsonObject> Msg);
    void ScheduleReconnect();

    TSharedPtr<FJsonObject> BuildToolSchema(const FKumiRegisterOptions& Opts) const;

    // .env parser
    static void LoadEnvFile(const FString& Path);
};
