using System;
using System.IO;

internal static class StagedInstall
{
    internal static void Commit(
        string staging,
        string target,
        RuntimeProbeResult probe)
    {
        if (probe == null || !probe.Success)
            throw new InvalidOperationException(
                "GPU-only 运行时验证失败，已保留现有版本。"
                + (probe == null ? "" : "\r\n" + probe.DisplayText));
        if (!Directory.Exists(staging))
            throw new DirectoryNotFoundException("暂存安装目录不存在。");

        string backup = target + ".backup-" + Guid.NewGuid().ToString("N");
        bool oldVersionMoved = false;
        try
        {
            if (Directory.Exists(target))
            {
                Directory.Move(target, backup);
                oldVersionMoved = true;
            }
            Directory.Move(staging, target);
        }
        catch
        {
            if (oldVersionMoved && Directory.Exists(backup))
            {
                if (Directory.Exists(target))
                    Directory.Delete(target, true);
                Directory.Move(backup, target);
            }
            throw;
        }

        if (Directory.Exists(backup))
        {
            try
            {
                Directory.Delete(backup, true);
            }
            catch (IOException)
            {
                // The new version is already committed; a stale backup is safe to remove later.
            }
            catch (UnauthorizedAccessException)
            {
                // Antivirus may still hold a file. Do not invalidate a successful commit.
            }
        }
    }
}
