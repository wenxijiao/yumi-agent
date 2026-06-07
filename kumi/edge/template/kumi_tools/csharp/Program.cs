using System;
using System.Threading;

/// <summary>
/// Standalone entry: add a small <c>.csproj</c> that references <c>kumi_sdk</c>, then <c>dotnet run</c>.
/// Remove this file when you integrate <see cref="KumiSetup.InitKumi"/> into your own app.
/// </summary>
internal static class KumiEdgeProgram
{
    private static void Main()
    {
        KumiSetup.InitKumi();
        Console.Error.WriteLine("Kumi edge running. Press Ctrl+C to exit.");
        Thread.Sleep(Timeout.Infinite);
    }
}
