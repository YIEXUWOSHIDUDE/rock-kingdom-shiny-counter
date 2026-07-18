using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class Uninstaller
{
    private const string ProductKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\RockKingdomShinyCounter";

    [STAThread]
    private static int Main(string[] args)
    {
        bool silent = Array.Exists(args, value => value.Equals("/SILENT", StringComparison.OrdinalIgnoreCase));
        string installDirectory = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        if (!silent)
        {
            DialogResult answer = MessageBox.Show(
                "确定卸载洛克王国异色保底计数器吗？\n计数和设置仍会保留在 AppData 中。",
                "卸载",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question);
            if (answer != DialogResult.Yes)
                return 1;
        }

        try
        {
            Registry.CurrentUser.DeleteSubKeyTree(ProductKey, false);
            DeleteShortcut(Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                "洛克王国异色保底计数器.lnk"));
            string startMenu = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
                "Programs", "洛克王国异色保底计数器");
            if (Directory.Exists(startMenu))
                Directory.Delete(startMenu, true);

            string command = "/c ping 127.0.0.1 -n 3 > nul & rmdir /s /q \"" + installDirectory + "\"";
            Process.Start(new ProcessStartInfo("cmd.exe", command)
            {
                CreateNoWindow = true,
                UseShellExecute = false,
                WindowStyle = ProcessWindowStyle.Hidden
            });
            if (!silent)
                MessageBox.Show("卸载已完成。", "卸载", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 0;
        }
        catch (Exception error)
        {
            if (!silent)
                MessageBox.Show(error.Message, "卸载失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 2;
        }
    }

    private static void DeleteShortcut(string path)
    {
        if (File.Exists(path))
            File.Delete(path);
    }
}
