using System;
using System.Collections.Generic;

internal static class CompatibilityTests
{
    private static int failures;

    private static void Main(string[] args)
    {
        if (args.Length == 2 && args[0] == "--detect")
        {
            Console.WriteLine(
                CompatibilityEvaluator.Evaluate(
                    CompatibilityDetector.Detect(args[1])).ToDisplayText());
            return;
        }
        Run("supported RTX 5070 can install", SupportedRtx5070CanInstall);
        Run("unsupported GPU blocks installation", UnsupportedGpuBlocksInstallation);
        Run("unknown GPU details warn without blocking", UnknownGpuDetailsWarnWithoutBlocking);
        Run("unsupported Windows or disk blocks installation", UnsupportedSystemBlocksInstallation);
        Run("nvidia-smi output becomes GPU snapshots", NvidiaSmiOutputBecomesGpuSnapshots);
        Run("GPU detection failure warns without blocking", GpuDetectionFailureWarnsWithoutBlocking);
        Run("native Windows build bypasses compatibility shims", NativeWindowsBuildIsAccurate);
        Run("WMI-only metrics stay warnings", WmiOnlyMetricsStayWarnings);
        if (failures != 0)
            Environment.Exit(1);
    }

    private static void SupportedRtx5070CanInstall()
    {
        CompatibilitySnapshot snapshot = new CompatibilitySnapshot();
        snapshot.Is64BitOperatingSystem = true;
        snapshot.WindowsBuild = 26100;
        snapshot.AvailableDiskBytes = 20L * 1024 * 1024 * 1024;
        snapshot.Gpus.Add(new GpuSnapshot(
            "NVIDIA GeForce RTX 5070",
            12L * 1024,
            "580.88",
            12,
            0));

        CompatibilityReport report = CompatibilityEvaluator.Evaluate(snapshot);

        Assert(report.CanInstall, report.ToDisplayText());
        Assert(!report.HasWarnings, report.ToDisplayText());
    }

    private static void UnsupportedGpuBlocksInstallation()
    {
        CompatibilitySnapshot snapshot = new CompatibilitySnapshot();
        snapshot.Is64BitOperatingSystem = true;
        snapshot.WindowsBuild = 26100;
        snapshot.AvailableDiskBytes = 20L * 1024 * 1024 * 1024;
        snapshot.Gpus.Add(new GpuSnapshot(
            "NVIDIA GeForce GTX 1060",
            3L * 1024,
            "581.29",
            6,
            1));

        CompatibilityReport report = CompatibilityEvaluator.Evaluate(snapshot);

        Assert(!report.CanInstall, report.ToDisplayText());
    }

    private static void UnknownGpuDetailsWarnWithoutBlocking()
    {
        CompatibilitySnapshot snapshot = new CompatibilitySnapshot();
        snapshot.Is64BitOperatingSystem = true;
        snapshot.WindowsBuild = 26100;
        snapshot.AvailableDiskBytes = 20L * 1024 * 1024 * 1024;
        snapshot.Gpus.Add(new GpuSnapshot(
            "NVIDIA GeForce RTX 3050 Laptop GPU",
            4L * 1024,
            "",
            0,
            0));

        CompatibilityReport report = CompatibilityEvaluator.Evaluate(snapshot);

        Assert(report.CanInstall, report.ToDisplayText());
        Assert(report.HasWarnings, report.ToDisplayText());
    }

    private static void UnsupportedSystemBlocksInstallation()
    {
        CompatibilitySnapshot snapshot = new CompatibilitySnapshot();
        snapshot.Is64BitOperatingSystem = false;
        snapshot.WindowsBuild = 17763;
        snapshot.AvailableDiskBytes = 3L * 1024 * 1024 * 1024;
        snapshot.Gpus.Add(new GpuSnapshot(
            "NVIDIA GeForce RTX 3060",
            12L * 1024,
            "581.29",
            8,
            6));

        CompatibilityReport report = CompatibilityEvaluator.Evaluate(snapshot);

        Assert(!report.CanInstall, report.ToDisplayText());
    }

    private static void NvidiaSmiOutputBecomesGpuSnapshots()
    {
        string output =
            "NVIDIA GeForce RTX 3050 Laptop GPU, 4096, 581.29, 8.6\r\n"
            + "NVIDIA GeForce RTX 5070, 12227, 580.88, 12.0\r\n";

        List<GpuSnapshot> gpus = CompatibilityDetector.ParseNvidiaSmiOutput(output);

        Assert(gpus.Count == 2, "expected two GPUs");
        Assert(gpus[0].MemoryMegabytes == 4096, "memory parse failed");
        Assert(gpus[0].ComputeMajor == 8 && gpus[0].ComputeMinor == 6, "compute parse failed");
        Assert(gpus[1].DriverVersion == "580.88", "driver parse failed");
    }

    private static void GpuDetectionFailureWarnsWithoutBlocking()
    {
        CompatibilitySnapshot snapshot = new CompatibilitySnapshot();
        snapshot.Is64BitOperatingSystem = true;
        snapshot.WindowsBuild = 26100;
        snapshot.AvailableDiskBytes = 20L * 1024 * 1024 * 1024;
        snapshot.GpuDetectionFailed = true;

        CompatibilityReport report = CompatibilityEvaluator.Evaluate(snapshot);

        Assert(report.CanInstall, report.ToDisplayText());
        Assert(report.HasWarnings, report.ToDisplayText());
    }

    private static void NativeWindowsBuildIsAccurate()
    {
        int build = CompatibilityDetector.GetWindowsBuild();

        Assert(build >= 19045, "unexpected Windows build " + build);
    }

    private static void WmiOnlyMetricsStayWarnings()
    {
        CompatibilitySnapshot snapshot = new CompatibilitySnapshot();
        snapshot.Is64BitOperatingSystem = true;
        snapshot.WindowsBuild = 26100;
        snapshot.AvailableDiskBytes = 20L * 1024 * 1024 * 1024;
        snapshot.Gpus.Add(new GpuSnapshot(
            "NVIDIA GeForce RTX 5070",
            1024,
            "",
            0,
            0,
            false));

        CompatibilityReport report = CompatibilityEvaluator.Evaluate(snapshot);

        Assert(report.CanInstall, report.ToDisplayText());
        Assert(report.HasWarnings, report.ToDisplayText());
    }

    private static void Run(string name, Action test)
    {
        try
        {
            test();
            Console.WriteLine("PASS " + name);
        }
        catch (Exception error)
        {
            failures++;
            Console.WriteLine("FAIL " + name + ": " + error.Message);
        }
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException(message);
    }
}
