using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

internal sealed class RuntimeProbeResult
{
    private RuntimeProbeResult(
        bool success,
        string stage,
        string message,
        string reportText)
    {
        Success = success;
        Stage = stage ?? "";
        Message = message ?? "";
        ReportText = reportText ?? "";
    }

    internal bool Success { get; private set; }
    internal string Stage { get; private set; }
    internal string Message { get; private set; }
    internal string ReportText { get; private set; }

    internal string DisplayText
    {
        get
        {
            string stage = string.IsNullOrWhiteSpace(Stage) ? "unknown" : Stage;
            string message = string.IsNullOrWhiteSpace(Message)
                ? "运行时探针没有返回错误说明。"
                : Message;
            return "阶段 " + stage + "：" + message
                + (string.IsNullOrWhiteSpace(ReportText)
                    ? ""
                    : "\r\n详细信息：" + ReportText);
        }
    }

    internal static RuntimeProbeResult FromProcess(int exitCode, string reportText)
    {
        try
        {
            JavaScriptSerializer serializer = new JavaScriptSerializer();
            Dictionary<string, object> payload =
                serializer.Deserialize<Dictionary<string, object>>(reportText ?? "");
            bool payloadOk = payload.ContainsKey("ok")
                && Convert.ToBoolean(payload["ok"]);
            string stage = payload.ContainsKey("stage")
                ? Convert.ToString(payload["stage"])
                : "";
            string message = payload.ContainsKey("message")
                ? Convert.ToString(payload["message"])
                : "";
            return new RuntimeProbeResult(
                exitCode == 0 && payloadOk,
                stage,
                message,
                reportText);
        }
        catch (Exception error)
        {
            return new RuntimeProbeResult(
                false,
                "probe_report",
                "无法读取 GPU 运行时探针结果：" + error.Message,
                reportText);
        }
    }

    internal static RuntimeProbeResult Failed(string stage, string message)
    {
        return new RuntimeProbeResult(false, stage, message, "");
    }
}

internal static class RuntimeProbeRunner
{
    internal static RuntimeProbeResult Run(
        string executable,
        string workingDirectory,
        int timeoutMilliseconds)
    {
        if (!File.Exists(executable))
            return RuntimeProbeResult.Failed(
                "probe_executable",
                "暂存版本缺少主程序，无法验证 GPU 运行时。");

        string report = Path.Combine(
            Path.GetTempPath(),
            "RKSC-runtime-" + Guid.NewGuid().ToString("N") + ".json");
        try
        {
            ProcessStartInfo start = new ProcessStartInfo(
                executable,
                "--probe-runtime \"" + report + "\"");
            start.WorkingDirectory = workingDirectory;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;

            using (Process process = Process.Start(start))
            {
                Task<string> standardOutput = process.StandardOutput.ReadToEndAsync();
                Task<string> standardError = process.StandardError.ReadToEndAsync();
                if (!process.WaitForExit(timeoutMilliseconds))
                {
                    process.Kill();
                    process.WaitForExit(5000);
                    return RuntimeProbeResult.Failed(
                        "probe_timeout",
                        "GPU 与 OCR 运行时验证超时。");
                }
                Task.WaitAll(
                    new Task[] { standardOutput, standardError },
                    5000);
                string errorText = standardError.IsCompleted
                    ? standardError.Result
                    : "";
                if (!File.Exists(report))
                    return RuntimeProbeResult.Failed(
                        "probe_report",
                        "暂存程序没有生成运行时报告。"
                        + (string.IsNullOrWhiteSpace(errorText)
                            ? ""
                            : " " + errorText.Trim()));
                return RuntimeProbeResult.FromProcess(
                    process.ExitCode,
                    File.ReadAllText(report));
            }
        }
        catch (Exception error)
        {
            return RuntimeProbeResult.Failed(
                "probe_process",
                "无法启动暂存程序验证 GPU：" + error.Message);
        }
        finally
        {
            try
            {
                if (File.Exists(report))
                    File.Delete(report);
            }
            catch (IOException)
            {
            }
        }
    }
}
