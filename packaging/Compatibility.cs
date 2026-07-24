using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Management;
using System.Runtime.InteropServices;
using System.Text;

internal enum CompatibilitySeverity
{
    Pass,
    Warning,
    Fail
}

internal sealed class CompatibilityCheck
{
    internal CompatibilityCheck(
        string name,
        CompatibilitySeverity severity,
        string detail)
    {
        Name = name;
        Severity = severity;
        Detail = detail;
    }

    internal string Name { get; private set; }
    internal CompatibilitySeverity Severity { get; private set; }
    internal string Detail { get; private set; }
}

internal sealed class GpuSnapshot
{
    internal GpuSnapshot(
        string name,
        long memoryMegabytes,
        string driverVersion,
        int computeMajor,
        int computeMinor)
        : this(
            name,
            memoryMegabytes,
            driverVersion,
            computeMajor,
            computeMinor,
            true)
    {
    }

    internal GpuSnapshot(
        string name,
        long memoryMegabytes,
        string driverVersion,
        int computeMajor,
        int computeMinor,
        bool metricsReliable)
    {
        Name = name;
        MemoryMegabytes = memoryMegabytes;
        DriverVersion = driverVersion;
        ComputeMajor = computeMajor;
        ComputeMinor = computeMinor;
        MetricsReliable = metricsReliable;
    }

    internal string Name { get; private set; }
    internal long MemoryMegabytes { get; private set; }
    internal string DriverVersion { get; private set; }
    internal int ComputeMajor { get; private set; }
    internal int ComputeMinor { get; private set; }
    internal bool MetricsReliable { get; private set; }
    internal bool HasComputeCapability
    {
        get { return ComputeMajor > 0; }
    }
}

internal sealed class CompatibilitySnapshot
{
    internal CompatibilitySnapshot()
    {
        Gpus = new List<GpuSnapshot>();
    }

    internal bool Is64BitOperatingSystem { get; set; }
    internal int WindowsBuild { get; set; }
    internal long AvailableDiskBytes { get; set; }
    internal bool GpuDetectionFailed { get; set; }
    internal List<GpuSnapshot> Gpus { get; private set; }
}

internal sealed class CompatibilityReport
{
    internal CompatibilityReport(IEnumerable<CompatibilityCheck> checks)
    {
        Checks = checks.ToList();
    }

    internal List<CompatibilityCheck> Checks { get; private set; }
    internal bool CanInstall
    {
        get { return Checks.All(item => item.Severity != CompatibilitySeverity.Fail); }
    }
    internal bool HasWarnings
    {
        get { return Checks.Any(item => item.Severity == CompatibilitySeverity.Warning); }
    }

    internal string ToDisplayText()
    {
        StringBuilder output = new StringBuilder();
        foreach (CompatibilityCheck check in Checks)
        {
            string marker = check.Severity == CompatibilitySeverity.Pass
                ? "✓"
                : check.Severity == CompatibilitySeverity.Warning ? "⚠" : "✕";
            output.AppendLine(marker + " " + check.Name + "：" + check.Detail);
        }
        return output.ToString().TrimEnd();
    }
}

internal static class CompatibilityEvaluator
{
    private const long MinimumDiskBytes = 8L * 1024 * 1024 * 1024;

    internal static CompatibilityReport Evaluate(CompatibilitySnapshot snapshot)
    {
        List<CompatibilityCheck> checks = new List<CompatibilityCheck>();
        checks.Add(new CompatibilityCheck(
            "Windows",
            snapshot.Is64BitOperatingSystem && snapshot.WindowsBuild >= 19045
                ? CompatibilitySeverity.Pass
                : CompatibilitySeverity.Fail,
            snapshot.Is64BitOperatingSystem
                ? "64 位，Build " + snapshot.WindowsBuild
                : "不是 64 位系统"));
        checks.Add(new CompatibilityCheck(
            "磁盘空间",
            snapshot.AvailableDiskBytes >= MinimumDiskBytes
                ? CompatibilitySeverity.Pass
                : CompatibilitySeverity.Fail,
            FormatGigabytes(snapshot.AvailableDiskBytes) + " GB 可用"));

        GpuSnapshot gpu = snapshot.Gpus
            .OrderByDescending(item => item.ComputeMajor)
            .ThenByDescending(item => item.ComputeMinor)
            .ThenByDescending(item => item.MemoryMegabytes)
            .FirstOrDefault();
        bool memoryKnown = gpu != null
            && gpu.MetricsReliable
            && gpu.MemoryMegabytes > 0;
        bool memorySupported = memoryKnown && gpu.MemoryMegabytes >= 4096;
        bool driverKnown = gpu != null
            && gpu.MetricsReliable
            && !string.IsNullOrWhiteSpace(gpu.DriverVersion);
        bool driverSupported = driverKnown && DriverAtLeast(gpu.DriverVersion, 580, 88);
        bool computeKnown = gpu != null
            && gpu.MetricsReliable
            && gpu.HasComputeCapability;
        bool computeSupported = computeKnown && SupportsComputeCapability(gpu);
        checks.Add(new CompatibilityCheck(
            "NVIDIA GPU",
            gpu != null
                ? CompatibilitySeverity.Pass
                : snapshot.GpuDetectionFailed
                    ? CompatibilitySeverity.Warning
                    : CompatibilitySeverity.Fail,
            gpu != null
                ? gpu.Name
                : snapshot.GpuDetectionFailed
                    ? "检测工具不可用，请安装后再次确认"
                    : "未检测到 NVIDIA GPU"));
        checks.Add(new CompatibilityCheck(
            "显存",
            !memoryKnown
                ? CompatibilitySeverity.Warning
                : memorySupported ? CompatibilitySeverity.Pass : CompatibilitySeverity.Fail,
            memoryKnown
                ? FormatGigabytes(gpu.MemoryMegabytes * 1024L * 1024L)
                    + " GB（最低 4 GB）"
                : "无法读取"));
        checks.Add(new CompatibilityCheck(
            "驱动",
            !driverKnown
                ? CompatibilitySeverity.Warning
                : driverSupported ? CompatibilitySeverity.Pass : CompatibilitySeverity.Fail,
            driverKnown
                ? gpu.DriverVersion + "（最低 580.88）"
                : "无法读取"));
        checks.Add(new CompatibilityCheck(
            "CUDA 计算能力",
            !computeKnown
                ? CompatibilitySeverity.Warning
                : computeSupported ? CompatibilitySeverity.Pass : CompatibilitySeverity.Fail,
            computeKnown
                ? gpu.ComputeMajor + "." + gpu.ComputeMinor
                    + "（最低 7.5，且安装包需包含对应架构）"
                : "无法读取"));
        return new CompatibilityReport(checks);
    }

    private static bool SupportsComputeCapability(GpuSnapshot gpu)
    {
        if (!gpu.HasComputeCapability
            || gpu.ComputeMajor < 7
            || (gpu.ComputeMajor == 7 && gpu.ComputeMinor < 5))
            return false;
        int[,] packageArchitectures =
        {
            { 7, 5 },
            { 8, 0 },
            { 8, 6 },
            { 9, 0 },
            { 10, 0 },
            { 12, 0 }
        };
        for (int index = 0; index < packageArchitectures.GetLength(0); index++)
        {
            if (packageArchitectures[index, 0] == gpu.ComputeMajor
                && packageArchitectures[index, 1] <= gpu.ComputeMinor)
                return true;
        }
        return false;
    }

    private static bool DriverAtLeast(string value, int minimumMajor, int minimumMinor)
    {
        string[] parts = (value ?? "").Split('.');
        int major;
        int minor;
        if (parts.Length < 2
            || !int.TryParse(parts[0], out major)
            || !int.TryParse(parts[1], out minor))
            return false;
        return major > minimumMajor || (major == minimumMajor && minor >= minimumMinor);
    }

    private static string FormatGigabytes(long bytes)
    {
        return (bytes / 1024d / 1024d / 1024d).ToString("0.0");
    }
}

internal static class CompatibilityDetector
{
    internal static CompatibilitySnapshot Detect(string installTarget)
    {
        CompatibilitySnapshot snapshot = new CompatibilitySnapshot();
        snapshot.Is64BitOperatingSystem = Environment.Is64BitOperatingSystem;
        snapshot.WindowsBuild = GetWindowsBuild();
        snapshot.AvailableDiskBytes = new DriveInfo(
            Path.GetPathRoot(installTarget)).AvailableFreeSpace;

        List<GpuSnapshot> nvidiaSmi = QueryNvidiaSmi();
        if (nvidiaSmi.Count > 0)
        {
            snapshot.Gpus.AddRange(nvidiaSmi);
            return snapshot;
        }

        List<GpuSnapshot> wmiGpus;
        if (TryQueryWmi(out wmiGpus))
            snapshot.Gpus.AddRange(wmiGpus);
        else
            snapshot.GpuDetectionFailed = true;
        return snapshot;
    }

    internal static int GetWindowsBuild()
    {
        RtlOsVersionInfo version = new RtlOsVersionInfo();
        version.Size = Marshal.SizeOf(typeof(RtlOsVersionInfo));
        try
        {
            if (RtlGetVersion(ref version) == 0)
                return version.Build;
        }
        catch (Exception)
        {
            // Fall back to the managed value on unusual Windows variants.
        }
        return Environment.OSVersion.Version.Build;
    }

    internal static List<GpuSnapshot> ParseNvidiaSmiOutput(string output)
    {
        List<GpuSnapshot> gpus = new List<GpuSnapshot>();
        string[] lines = (output ?? "").Split(
            new[] { "\r\n", "\n" },
            StringSplitOptions.RemoveEmptyEntries);
        foreach (string line in lines)
        {
            string[] fields = line.Split(',');
            if (fields.Length < 3)
                continue;
            long memory;
            if (!long.TryParse(
                fields[1].Trim(),
                NumberStyles.Integer,
                CultureInfo.InvariantCulture,
                out memory))
                memory = 0;
            int computeMajor = 0;
            int computeMinor = 0;
            string[] compute = fields.Length >= 4
                ? fields[3].Trim().Split('.')
                : new string[0];
            if (compute.Length >= 2)
            {
                int.TryParse(compute[0], out computeMajor);
                int.TryParse(compute[1], out computeMinor);
            }
            gpus.Add(new GpuSnapshot(
                fields[0].Trim(),
                memory,
                fields[2].Trim(),
                computeMajor,
                computeMinor));
        }
        return gpus;
    }

    private static List<GpuSnapshot> QueryNvidiaSmi()
    {
        string output = RunNvidiaSmi(
            "--query-gpu=name,memory.total,driver_version,compute_cap "
            + "--format=csv,noheader,nounits");
        List<GpuSnapshot> gpus = ParseNvidiaSmiOutput(output);
        if (gpus.Count > 0)
            return gpus;
        output = RunNvidiaSmi(
            "--query-gpu=name,memory.total,driver_version "
            + "--format=csv,noheader,nounits");
        return ParseNvidiaSmiOutput(output);
    }

    private static string RunNvidiaSmi(string arguments)
    {
        string windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        string[] candidates =
        {
            "nvidia-smi.exe",
            Path.Combine(windows, "System32", "nvidia-smi.exe"),
            Path.Combine(programFiles, "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe")
        };
        foreach (string candidate in candidates.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                ProcessStartInfo start = new ProcessStartInfo(candidate, arguments);
                start.UseShellExecute = false;
                start.CreateNoWindow = true;
                start.RedirectStandardOutput = true;
                start.RedirectStandardError = true;
                using (Process process = Process.Start(start))
                {
                    if (!process.WaitForExit(5000))
                    {
                        process.Kill();
                        continue;
                    }
                    if (process.ExitCode == 0)
                        return process.StandardOutput.ReadToEnd();
                }
            }
            catch (Exception)
            {
                // Continue to the known install locations, then WMI.
            }
        }
        return "";
    }

    private static bool TryQueryWmi(out List<GpuSnapshot> gpus)
    {
        gpus = new List<GpuSnapshot>();
        try
        {
            using (ManagementObjectSearcher searcher = new ManagementObjectSearcher(
                "SELECT Name, AdapterRAM FROM Win32_VideoController"))
            using (ManagementObjectCollection results = searcher.Get())
            {
                foreach (ManagementObject video in results)
                {
                    string name = Convert.ToString(video["Name"]);
                    if (string.IsNullOrWhiteSpace(name)
                        || name.IndexOf("NVIDIA", StringComparison.OrdinalIgnoreCase) < 0)
                        continue;
                    long memoryBytes = 0;
                    try
                    {
                        if (video["AdapterRAM"] != null)
                            memoryBytes = Convert.ToInt64(video["AdapterRAM"]);
                    }
                    catch (Exception)
                    {
                        memoryBytes = 0;
                    }
                    gpus.Add(new GpuSnapshot(
                        name,
                        memoryBytes / 1024 / 1024,
                        "",
                        0,
                        0,
                        false));
                }
            }
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct RtlOsVersionInfo
    {
        internal int Size;
        internal int Major;
        internal int Minor;
        internal int Build;
        internal int Platform;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)]
        internal string ServicePack;
    }

    [DllImport("ntdll.dll", CharSet = CharSet.Unicode)]
    private static extern int RtlGetVersion(ref RtlOsVersionInfo version);
}
