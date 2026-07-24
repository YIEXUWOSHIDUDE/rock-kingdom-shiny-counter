using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class Installer
{
    internal const string Version = "0.4.1";
    internal const string ProductName = "洛克王国异色保底计数器";
    private const string ProductKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\RockKingdomShinyCounter";
    private static readonly byte[] FooterMagic = Encoding.ASCII.GetBytes("RKSCZIP1");

    [STAThread]
    private static int Main(string[] args)
    {
        bool silent = args.Any(value => value.Equals("/SILENT", StringComparison.OrdinalIgnoreCase));
        bool testMode = args.Any(value => value.Equals("/TEST", StringComparison.OrdinalIgnoreCase));
        string overridePath = Environment.GetEnvironmentVariable("RKSC_INSTALL_DIR");
        string target = string.IsNullOrWhiteSpace(overridePath)
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "RockKingdomShinyCounter")
            : Path.GetFullPath(overridePath);

        if (silent)
        {
            try
            {
                Install(target, !testMode, null);
                return 0;
            }
            catch (Exception error)
            {
                File.WriteAllText(Path.Combine(Path.GetTempPath(), "RockKingdomShinyCounter-install-error.txt"), error.ToString());
                return 2;
            }
        }

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new InstallerForm(target));
        return 0;
    }

    internal static void Install(string target, bool createShellEntries, Action<string> status)
    {
        Action<string> report = status ?? (_ => { });
        string root = Path.GetPathRoot(target);
        DriveInfo drive = new DriveInfo(root);
        if (drive.AvailableFreeSpace < 6L * 1024 * 1024 * 1024)
            throw new IOException("安装盘可用空间不足。请至少再腾出 6 GB；连同安装包本身建议预留 8 GB。 ");

        string temporaryRoot = Path.Combine(Path.GetTempPath(), "RKSC-Install-" + Guid.NewGuid().ToString("N"));
        string package = Path.Combine(temporaryRoot, "payload.zip");
        string staging = target + ".new-" + Guid.NewGuid().ToString("N");
        Directory.CreateDirectory(temporaryRoot);
        try
        {
            report("正在读取安装数据……");
            CopyAppendedPayload(package);
            report("正在解压 CUDA 13 与 OCR 文件……");
            ZipFile.ExtractToDirectory(package, staging);
            ValidateStaging(staging);

            report("正在替换旧版本……");
            if (Directory.Exists(target))
                Directory.Delete(target, true);
            Directory.Move(staging, target);

            if (createShellEntries)
            {
                report("正在创建快捷方式……");
                CreateShellEntries(target);
                RegisterUninstaller(target);
            }
            report("安装完成");
        }
        finally
        {
            if (Directory.Exists(staging))
                Directory.Delete(staging, true);
            if (Directory.Exists(temporaryRoot))
                Directory.Delete(temporaryRoot, true);
        }
    }

    private static void CopyAppendedPayload(string destination)
    {
        string executable = Process.GetCurrentProcess().MainModule.FileName;
        using (FileStream source = File.OpenRead(executable))
        {
            if (source.Length < 16)
                throw new InvalidDataException("安装包数据不完整。");
            source.Seek(-16, SeekOrigin.End);
            byte[] lengthBytes = new byte[8];
            byte[] magic = new byte[8];
            ReadExactly(source, lengthBytes);
            ReadExactly(source, magic);
            if (!magic.SequenceEqual(FooterMagic))
                throw new InvalidDataException("安装包签名无效，请重新下载。");
            long payloadLength = BitConverter.ToInt64(lengthBytes, 0);
            long payloadOffset = source.Length - 16 - payloadLength;
            if (payloadLength <= 0 || payloadOffset <= 0)
                throw new InvalidDataException("安装包长度无效，请重新下载。");

            source.Position = payloadOffset;
            using (FileStream output = File.Create(destination))
            {
                byte[] buffer = new byte[1024 * 1024];
                long remaining = payloadLength;
                while (remaining > 0)
                {
                    int count = source.Read(buffer, 0, (int)Math.Min(buffer.Length, remaining));
                    if (count <= 0)
                        throw new EndOfStreamException("安装包数据提前结束。");
                    output.Write(buffer, 0, count);
                    remaining -= count;
                }
            }
        }
    }

    private static void ReadExactly(Stream stream, byte[] buffer)
    {
        int offset = 0;
        while (offset < buffer.Length)
        {
            int count = stream.Read(buffer, offset, buffer.Length - offset);
            if (count <= 0)
                throw new EndOfStreamException();
            offset += count;
        }
    }

    private static void ValidateStaging(string staging)
    {
        RequireFile(Path.Combine(staging, "RockKingdomShinyCounter.exe"), null);
        RequireFile(
            Path.Combine(staging, "_internal", "ocr-models", "craft_mlt_25k.pth"),
            "4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17");
        RequireFile(
            Path.Combine(staging, "_internal", "ocr-models", "zh_sim_g2.pth"),
            "cb678fdef09d651e7763ca551ad790dc89f0b2e3d2a640484330e338fb574c7a");
        RequireFile(Path.Combine(staging, "Uninstall.exe"), null);
    }

    private static void RequireFile(string path, string expectedHash)
    {
        if (!File.Exists(path))
            throw new InvalidDataException("安装包缺少文件：" + Path.GetFileName(path));
        if (expectedHash == null)
            return;
        using (SHA256 sha = SHA256.Create())
        using (FileStream input = File.OpenRead(path))
        {
            string actual = BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
            if (actual != expectedHash)
                throw new InvalidDataException("OCR 模型校验失败：" + Path.GetFileName(path));
        }
    }

    private static void CreateShellEntries(string target)
    {
        string executable = Path.Combine(target, "RockKingdomShinyCounter.exe");
        string desktop = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), ProductName + ".lnk");
        string startMenu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu), "Programs", ProductName);
        Directory.CreateDirectory(startMenu);
        CreateShortcut(desktop, executable, target);
        CreateShortcut(Path.Combine(startMenu, ProductName + ".lnk"), executable, target);
        CreateShortcut(Path.Combine(startMenu, "卸载.lnk"), Path.Combine(target, "Uninstall.exe"), target);
    }

    private static void CreateShortcut(string shortcutPath, string targetPath, string workingDirectory)
    {
        Type shellType = Type.GetTypeFromProgID("WScript.Shell");
        dynamic shell = Activator.CreateInstance(shellType);
        dynamic shortcut = shell.CreateShortcut(shortcutPath);
        shortcut.TargetPath = targetPath;
        shortcut.WorkingDirectory = workingDirectory;
        shortcut.Description = ProductName;
        shortcut.Save();
    }

    private static void RegisterUninstaller(string target)
    {
        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(ProductKey))
        {
            key.SetValue("DisplayName", ProductName);
            key.SetValue("DisplayVersion", Version);
            key.SetValue("Publisher", "RockKingdomShinyCounter");
            key.SetValue("InstallLocation", target);
            key.SetValue("DisplayIcon", Path.Combine(target, "RockKingdomShinyCounter.exe"));
            key.SetValue("UninstallString", "\"" + Path.Combine(target, "Uninstall.exe") + "\"");
            key.SetValue("NoModify", 1, RegistryValueKind.DWord);
            key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
        }
    }

    private sealed class InstallerForm : Form
    {
        private readonly string target;
        private readonly Label status;
        private readonly ProgressBar progress;
        private readonly Button install;
        private readonly CheckBox launch;

        internal InstallerForm(string targetPath)
        {
            target = targetPath;
            Text = ProductName + " 安装程序 v" + Version;
            ClientSize = new Size(570, 285);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Microsoft YaHei UI", 10F);

            Label title = new Label { Left = 26, Top = 24, Width = 520, Height = 32, Text = ProductName + "  v" + Version, Font = new Font(Font.FontFamily, 17F, FontStyle.Bold) };
            Label requirements = new Label { Left = 28, Top = 72, Width = 510, Height = 70, Text = "最低要求：Windows 10/11 x64、NVIDIA RTX 20/30/40/50、\n驱动 580.88 或更高、4 GB 显存、8 GB 可用磁盘空间。\n本版本只使用 GPU，不会降级到 CPU。" };
            status = new Label { Left = 28, Top = 155, Width = 510, Height = 26, Text = "安装位置：" + target };
            progress = new ProgressBar { Left = 28, Top = 188, Width = 510, Height = 20, Style = ProgressBarStyle.Blocks };
            launch = new CheckBox { Left = 28, Top = 226, Width = 260, Text = "安装完成后启动", Checked = true };
            install = new Button { Left = 403, Top = 220, Width = 135, Height = 36, Text = "安装" };
            install.Click += BeginInstall;
            Controls.AddRange(new Control[] { title, requirements, status, progress, launch, install });
        }

        private async void BeginInstall(object sender, EventArgs e)
        {
            install.Enabled = false;
            launch.Enabled = false;
            progress.Style = ProgressBarStyle.Marquee;
            try
            {
                await Task.Run(() => Install(target, true, message => BeginInvoke((Action)(() => status.Text = message))));
                progress.Style = ProgressBarStyle.Blocks;
                progress.Value = 100;
                install.Text = "完成";
                if (launch.Checked)
                    Process.Start(Path.Combine(target, "RockKingdomShinyCounter.exe"));
                MessageBox.Show("安装完成。", ProductName, MessageBoxButtons.OK, MessageBoxIcon.Information);
                Close();
            }
            catch (Exception error)
            {
                progress.Style = ProgressBarStyle.Blocks;
                status.Text = "安装失败";
                install.Enabled = true;
                launch.Enabled = true;
                MessageBox.Show(error.Message, "安装失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }
}
