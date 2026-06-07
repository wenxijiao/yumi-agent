#include "KumiSetup.h"

FKumiAgent* InitKumi()
{
    FKumiAgent* Agent = new FKumiAgent(KumiConnectionCode, KumiEdgeName);

    // ── Register tools ──

    // FKumiRegisterOptions JumpOpts;
    // JumpOpts.Name = TEXT("jump");
    // JumpOpts.Description = TEXT("Make the character jump");
    // JumpOpts.Parameters = {
    //     { TEXT("height"), TEXT("number"), TEXT("Jump height in meters"), true },
    // };
    // JumpOpts.Handler.BindLambda([](const FKumiToolArguments& Args) -> FString {
    //     double Height = Args.GetNumber(TEXT("height"), 1.0);
    //     return FString::Printf(TEXT("Jumped %.1f meters"), Height);
    // });
    // Agent->RegisterTool(MoveTemp(JumpOpts));

    // Dangerous tools: user confirms in the Kumi web UI or `kumi --chat`:
    // FKumiRegisterOptions DeleteOpts;
    // DeleteOpts.Name = TEXT("delete_all");
    // DeleteOpts.Description = TEXT("Delete all data");
    // DeleteOpts.bRequireConfirmation = true;
    // DeleteOpts.Handler.BindLambda([](const FKumiToolArguments&) -> FString {
    //     return TEXT("Deleted everything");
    // });
    // Agent->RegisterTool(MoveTemp(DeleteOpts));

    Agent->RunInBackground();
    return Agent;
}
