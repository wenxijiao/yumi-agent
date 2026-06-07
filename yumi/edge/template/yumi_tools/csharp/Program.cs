using System;
using System.Threading;

/// <summary>
/// Standalone entry: add a small <c>.csproj</c> that references <c>yumi_sdk</c>, then <c>dotnet run</c>.
/// Remove this file when you integrate <see cref="YumiSetup.InitYumi"/> into your own app.
/// </summary>
internal static class YumiEdgeProgram
{
    private static void Main()
    {
        YumiSetup.InitYumi();
        Console.Error.WriteLine("Yumi edge running. Press Ctrl+C to exit.");
        Thread.Sleep(Timeout.Infinite);
    }
}
