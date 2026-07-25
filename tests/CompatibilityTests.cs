using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;

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
        Run("unknown GPU details block GPU-only installation", UnknownGpuDetailsBlockGpuOnlyInstallation);
        Run("unsupported Windows or disk blocks installation", UnsupportedSystemBlocksInstallation);
        Run("4 GB free space blocks installation", FourGigabytesBlocksInstallation);
        Run("nvidia-smi output becomes GPU snapshots", NvidiaSmiOutputBecomesGpuSnapshots);
        Run("GPU detection failure blocks GPU-only installation", GpuDetectionFailureBlocksGpuOnlyInstallation);
        Run("native Windows build bypasses compatibility shims", NativeWindowsBuildIsAccurate);
        Run("WMI-only metrics block until runtime is verified", WmiOnlyMetricsBlockUntilRuntimeIsVerified);
        Run("failed packaged runtime probe blocks replacement", FailedPackagedRuntimeProbeBlocksReplacement);
        Run("failed runtime probe preserves installed version", FailedRuntimeProbePreservesInstalledVersion);
        Run("successful runtime probe commits staged version", SuccessfulRuntimeProbeCommitsStagedVersion);
        Run("payload manifest rejects unexpected files", PayloadManifestRejectsUnexpectedFiles);
        Run("embedded payload extracts without a temporary copy", EmbeddedPayloadExtractsWithoutTemporaryCopy);
        Run("installer version comes from embedded VERSION", InstallerVersionComesFromEmbeddedVersion);
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

    private static void InstallerVersionComesFromEmbeddedVersion()
    {
        string expected = File.ReadAllText("VERSION").Trim();

        Assert(ProductVersion.Current == expected, "embedded installer version drifted");
    }

    private static void FourGigabytesBlocksInstallation()
    {
        CompatibilitySnapshot snapshot = new CompatibilitySnapshot();
        snapshot.Is64BitOperatingSystem = true;
        snapshot.WindowsBuild = 26100;
        snapshot.AvailableDiskBytes = 4L * 1024 * 1024 * 1024;
        snapshot.Gpus.Add(new GpuSnapshot(
            "NVIDIA GeForce RTX 5070",
            12L * 1024,
            "580.88",
            12,
            0));

        CompatibilityReport report = CompatibilityEvaluator.Evaluate(snapshot);

        Assert(!report.CanInstall, report.ToDisplayText());
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

    private static void UnknownGpuDetailsBlockGpuOnlyInstallation()
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

        Assert(!report.CanInstall, report.ToDisplayText());
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

    private static void GpuDetectionFailureBlocksGpuOnlyInstallation()
    {
        CompatibilitySnapshot snapshot = new CompatibilitySnapshot();
        snapshot.Is64BitOperatingSystem = true;
        snapshot.WindowsBuild = 26100;
        snapshot.AvailableDiskBytes = 20L * 1024 * 1024 * 1024;
        snapshot.GpuDetectionFailed = true;

        CompatibilityReport report = CompatibilityEvaluator.Evaluate(snapshot);

        Assert(!report.CanInstall, report.ToDisplayText());
        Assert(report.HasWarnings, report.ToDisplayText());
    }

    private static void NativeWindowsBuildIsAccurate()
    {
        int build = CompatibilityDetector.GetWindowsBuild();

        Assert(build >= 19045, "unexpected Windows build " + build);
    }

    private static void WmiOnlyMetricsBlockUntilRuntimeIsVerified()
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

        Assert(!report.CanInstall, report.ToDisplayText());
        Assert(report.HasWarnings, report.ToDisplayText());
    }

    private static void FailedPackagedRuntimeProbeBlocksReplacement()
    {
        RuntimeProbeResult result = RuntimeProbeResult.FromProcess(
            4,
            "{\"ok\":false,\"stage\":\"cuda_available\","
            + "\"message\":\"CUDA 不可用；不允许 CPU 回退。\","
            + "\"details\":{\"torch\":\"2.13.0+cu130\","
            + "\"cuda_build\":\"13.0\",\"driver\":\"561.09\"}}");

        Assert(!result.Success, "failed runtime probe must block replacement");
        Assert(result.DisplayText.Contains("cuda_available"), result.DisplayText);
        Assert(result.DisplayText.Contains("不允许 CPU"), result.DisplayText);
        Assert(result.DisplayText.Contains("2.13.0+cu130"), result.DisplayText);
        Assert(result.DisplayText.Contains("561.09"), result.DisplayText);
    }

    private static void FailedRuntimeProbePreservesInstalledVersion()
    {
        string root = Path.Combine(
            Path.GetTempPath(),
            "RKSC-transaction-test-" + Guid.NewGuid().ToString("N"));
        string target = Path.Combine(root, "current");
        string staging = Path.Combine(root, "staging");
        Directory.CreateDirectory(target);
        Directory.CreateDirectory(staging);
        File.WriteAllText(Path.Combine(target, "version.txt"), "old");
        File.WriteAllText(Path.Combine(staging, "version.txt"), "new");
        try
        {
            bool blocked = false;
            try
            {
                StagedInstall.Commit(
                    staging,
                    target,
                    RuntimeProbeResult.FromProcess(
                        4,
                        "{\"ok\":false,\"stage\":\"cuda_available\","
                        + "\"message\":\"不允许 CPU 回退\",\"details\":{}}"));
            }
            catch (InvalidOperationException)
            {
                blocked = true;
            }

            Assert(blocked, "failed runtime probe must stop commit");
            Assert(
                File.ReadAllText(Path.Combine(target, "version.txt")) == "old",
                "installed version was modified");
            Assert(Directory.Exists(staging), "failed staging should remain for diagnostics");
        }
        finally
        {
            Directory.Delete(root, true);
        }
    }

    private static void SuccessfulRuntimeProbeCommitsStagedVersion()
    {
        string root = Path.Combine(
            Path.GetTempPath(),
            "RKSC-transaction-test-" + Guid.NewGuid().ToString("N"));
        string target = Path.Combine(root, "current");
        string staging = Path.Combine(root, "staging");
        Directory.CreateDirectory(target);
        Directory.CreateDirectory(staging);
        File.WriteAllText(Path.Combine(target, "version.txt"), "old");
        File.WriteAllText(Path.Combine(staging, "version.txt"), "new");
        try
        {
            StagedInstall.Commit(
                staging,
                target,
                RuntimeProbeResult.FromProcess(
                    0,
                    "{\"ok\":true,\"stage\":\"complete\","
                    + "\"message\":\"GPU 运行时验证通过\",\"details\":{}}"));

            Assert(
                File.ReadAllText(Path.Combine(target, "version.txt")) == "new",
                "staged version was not committed");
            Assert(!Directory.Exists(staging), "staging directory still exists");
            Assert(
                Directory.GetDirectories(root, "current.backup-*").Length == 0,
                "successful commit left a backup directory");
        }
        finally
        {
            Directory.Delete(root, true);
        }
    }

    private static void PayloadManifestRejectsUnexpectedFiles()
    {
        string root = Path.Combine(
            Path.GetTempPath(),
            "RKSC-manifest-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        string payload = Path.Combine(root, "app.bin");
        File.WriteAllText(payload, "trusted");
        string digest;
        using (SHA256 sha = SHA256.Create())
        using (FileStream input = File.OpenRead(payload))
        {
            digest = BitConverter.ToString(sha.ComputeHash(input))
                .Replace("-", "")
                .ToLowerInvariant();
        }
        File.WriteAllText(
            Path.Combine(root, "MANIFEST.sha256.json"),
            "{\"files\":[{\"path\":\"app.bin\",\"bytes\":7,\"sha256\":\""
            + digest
            + "\"}]}");
        try
        {
            PayloadManifestValidator.Validate(root);
            File.WriteAllText(Path.Combine(root, "unexpected.bin"), "extra");
            bool rejected = false;
            try
            {
                PayloadManifestValidator.Validate(root);
            }
            catch (InvalidDataException)
            {
                rejected = true;
            }
            Assert(rejected, "unexpected payload file was accepted");
        }
        finally
        {
            Directory.Delete(root, true);
        }
    }

    private static void EmbeddedPayloadExtractsWithoutTemporaryCopy()
    {
        string root = Path.Combine(
            Path.GetTempPath(),
            "RKSC-payload-test-" + Guid.NewGuid().ToString("N"));
        string installer = Path.Combine(root, "setup.exe");
        string target = Path.Combine(root, "app");
        Directory.CreateDirectory(root);
        try
        {
            byte[] payload;
            using (MemoryStream buffer = new MemoryStream())
            {
                using (ZipArchive archive = new ZipArchive(
                    buffer,
                    ZipArchiveMode.Create,
                    true))
                {
                    ZipArchiveEntry entry = archive.CreateEntry("hello.txt");
                    using (Stream output = entry.Open())
                    {
                        byte[] contents = Encoding.UTF8.GetBytes("hello GPU");
                        output.Write(contents, 0, contents.Length);
                    }
                }
                payload = buffer.ToArray();
            }
            using (FileStream output = File.Create(installer))
            {
                byte[] stub = Encoding.ASCII.GetBytes("MZ-test-stub");
                output.Write(stub, 0, stub.Length);
                output.Write(payload, 0, payload.Length);
                byte[] length = BitConverter.GetBytes((long)payload.Length);
                output.Write(length, 0, length.Length);
                byte[] magic = Encoding.ASCII.GetBytes("RKSCZIP1");
                output.Write(magic, 0, magic.Length);
            }

            AppendedPayload.Extract(installer, target);

            Assert(
                File.ReadAllText(Path.Combine(target, "hello.txt")) == "hello GPU",
                "embedded ZIP was not extracted");
            Assert(
                Directory.GetFiles(root, "payload.zip", SearchOption.AllDirectories).Length == 0,
                "payload was copied to a temporary ZIP");
        }
        finally
        {
            Directory.Delete(root, true);
        }
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
