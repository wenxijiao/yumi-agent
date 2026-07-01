#include "YumiSetup.h"

FYumiAgent* InitYumi()
{
    FYumiAgent* Agent = new FYumiAgent(YumiConnectionCode, YumiEdgeName);

    // ── Register tools ──

    // Example tool — replace with your own. Registered live in "pinned" mode.
    FYumiRegisterOptions PingOpts;
    PingOpts.Name = TEXT("ping");
    PingOpts.Description = TEXT("Ping the edge and echo a message back");
    PingOpts.Mode = TEXT("pinned");
    PingOpts.Parameters = {
        { TEXT("message"), TEXT("string"), TEXT("Text to echo back."), false },
    };
    PingOpts.Handler.BindLambda([](const FYumiToolArguments& Args) -> FString {
        FString Message = Args.GetString(TEXT("message"), TEXT("hello"));
        return TEXT("pong: ") + Message;
    });
    Agent->RegisterTool(MoveTemp(PingOpts));

    // FYumiRegisterOptions JumpOpts;
    // JumpOpts.Name = TEXT("jump");
    // JumpOpts.Description = TEXT("Make the character jump");
    // JumpOpts.Parameters = {
    //     { TEXT("height"), TEXT("number"), TEXT("Jump height in meters"), true },
    // };
    // JumpOpts.Handler.BindLambda([](const FYumiToolArguments& Args) -> FString {
    //     double Height = Args.GetNumber(TEXT("height"), 1.0);
    //     return FString::Printf(TEXT("Jumped %.1f meters"), Height);
    // });
    // Agent->RegisterTool(MoveTemp(JumpOpts));

    // Dangerous tools: user confirms in the Yumi web UI or `yumi --chat`:
    // FYumiRegisterOptions DeleteOpts;
    // DeleteOpts.Name = TEXT("delete_all");
    // DeleteOpts.Description = TEXT("Delete all data");
    // DeleteOpts.bRequireConfirmation = true;
    // DeleteOpts.Handler.BindLambda([](const FYumiToolArguments&) -> FString {
    //     return TEXT("Deleted everything");
    // });
    // Agent->RegisterTool(MoveTemp(DeleteOpts));

    Agent->RunInBackground();
    return Agent;
}
