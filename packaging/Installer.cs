using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class Installer
{
    internal static readonly string Version = ProductVersion.Current;
    internal const string ProductName = "洛克王国异色保底计数器";
    private const string ProductKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\RockKingdomShinyCounter";

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
                if (!testMode)
                {
                    CompatibilityReport compatibility =
                        CompatibilityEvaluator.Evaluate(
                            CompatibilityDetector.Detect(target));
                    if (!compatibility.CanInstall)
                        throw new InvalidOperationException(
                            "当前电脑不满足最低要求：\r\n"
                            + compatibility.ToDisplayText());
                }
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

    internal static string Install(string target, bool createShellEntries, Action<string> status)
    {
        Action<string> report = status ?? (_ => { });
        string root = Path.GetPathRoot(target);
        DriveInfo drive = new DriveInfo(root);
        if (drive.AvailableFreeSpace < CompatibilityEvaluator.MinimumDiskBytes)
            throw new IOException(
                "安装盘可用空间不足。请至少预留 "
                + CompatibilityEvaluator.MinimumDiskGigabytes
                + " GB。");

        string staging = target + ".new-" + Guid.NewGuid().ToString("N");
        try
        {
            report("正在从安装包解压 CUDA 13 与 OCR 文件……");
            AppendedPayload.Extract(
                Process.GetCurrentProcess().MainModule.FileName,
                staging);
            ValidateStaging(staging);

            report("正在验证 CUDA 与 EasyOCR GPU 运行时……");
            RuntimeProbeResult runtime = RuntimeProbeRunner.Run(
                Path.Combine(staging, "RockKingdomShinyCounter.exe"),
                staging,
                180000);
            if (!runtime.Success)
                throw new InvalidOperationException(
                    "GPU-only 运行时验证失败，安装已停止且现有版本未被替换。\r\n"
                    + runtime.DisplayText);

            report("正在安全替换旧版本……");
            StagedInstall.Commit(staging, target, runtime);

            string shellWarning = null;
            if (createShellEntries)
            {
                try
                {
                    report("正在创建快捷方式……");
                    CreateShellEntries(target);
                    RegisterUninstaller(target);
                }
                catch (Exception error)
                {
                    shellWarning = "主程序已安装，但创建快捷方式或卸载信息失败："
                        + error.Message;
                }
            }
            report(shellWarning ?? "安装完成");
            return shellWarning;
        }
        finally
        {
            DeleteDirectoryBestEffort(staging);
        }
    }

    private static void DeleteDirectoryBestEffort(string path)
    {
        try
        {
            if (Directory.Exists(path))
                Directory.Delete(path, true);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    private static void ValidateStaging(string staging)
    {
        RequireFile(Path.Combine(staging, "RockKingdomShinyCounter.exe"));
        RequireFile(Path.Combine(staging, "Uninstall.exe"));
        PayloadManifestValidator.Validate(staging);
    }

    private static void RequireFile(string path)
    {
        if (!File.Exists(path))
            throw new InvalidDataException("安装包缺少文件：" + Path.GetFileName(path));
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
        private readonly Button recheck;
        private readonly CheckBox launch;
        private readonly ListView compatibility;
        private readonly Label compatibilitySummary;
        private CompatibilityReport compatibilityReport;

        internal InstallerForm(string targetPath)
        {
            target = targetPath;
            Text = ProductName + " 安装程序 v" + Version;
            ClientSize = new Size(650, 510);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Microsoft YaHei UI", 10F);

            Label title = new Label { Left = 26, Top = 20, Width = 590, Height = 34, Text = ProductName + "  v" + Version, Font = new Font(Font.FontFamily, 17F, FontStyle.Bold) };
            Label requirements = new Label { Left = 28, Top = 62, Width = 590, Height = 60, Text = "最低要求：Windows 10 22H2 / Windows 11 x64、NVIDIA RTX 20/30/40/50、\n驱动 580.88 或更高、4 GB 显存、" + CompatibilityEvaluator.MinimumDiskGigabytes + " GB 可用磁盘空间；只使用 GPU，不降级到 CPU。" };
            Label compatibilityTitle = new Label { Left = 28, Top = 130, Width = 590, Height = 24, Text = "安装前兼容性检测", Font = new Font(Font.FontFamily, 10F, FontStyle.Bold) };
            compatibility = new ListView { Left = 28, Top = 158, Width = 590, Height = 180, View = View.List, HeaderStyle = ColumnHeaderStyle.None, MultiSelect = false, HideSelection = false };
            compatibility.Items.Add("正在检测系统和 NVIDIA GPU……");
            compatibilitySummary = new Label { Left = 28, Top = 346, Width = 590, Height = 34, Text = "请稍候……", Font = new Font(Font.FontFamily, 9F, FontStyle.Bold) };
            status = new Label { Left = 28, Top = 388, Width = 590, Height = 26, Text = "安装位置：" + target };
            progress = new ProgressBar { Left = 28, Top = 418, Width = 590, Height = 20, Style = ProgressBarStyle.Marquee };
            launch = new CheckBox { Left = 28, Top = 461, Width = 260, Text = "安装完成后启动", Checked = true };
            recheck = new Button { Left = 333, Top = 454, Width = 135, Height = 36, Text = "重新检测", Enabled = false };
            install = new Button { Left = 483, Top = 454, Width = 135, Height = 36, Text = "安装", Enabled = false };
            recheck.Click += async (sender, args) => await CheckCompatibilityAsync();
            install.Click += BeginInstall;
            Shown += async (sender, args) => await CheckCompatibilityAsync();
            Controls.AddRange(new Control[] { title, requirements, compatibilityTitle, compatibility, compatibilitySummary, status, progress, launch, recheck, install });
        }

        private async Task CheckCompatibilityAsync()
        {
            install.Enabled = false;
            recheck.Enabled = false;
            progress.Style = ProgressBarStyle.Marquee;
            compatibility.Items.Clear();
            compatibility.Items.Add("正在检测 Windows、磁盘和 NVIDIA GPU……");
            compatibilitySummary.ForeColor = SystemColors.ControlText;
            compatibilitySummary.Text = "请稍候……";
            try
            {
                compatibilityReport = await Task.Run(() =>
                    CompatibilityEvaluator.Evaluate(
                        CompatibilityDetector.Detect(target)));
                compatibility.Items.Clear();
                foreach (CompatibilityCheck check in compatibilityReport.Checks)
                {
                    string marker = check.Severity == CompatibilitySeverity.Pass
                        ? "✓"
                        : check.Severity == CompatibilitySeverity.Warning ? "⚠" : "✕";
                    ListViewItem item = new ListViewItem(
                        marker + "  " + check.Name + "：" + check.Detail);
                    item.ForeColor = check.Severity == CompatibilitySeverity.Pass
                        ? Color.DarkGreen
                        : check.Severity == CompatibilitySeverity.Warning
                            ? Color.DarkOrange
                            : Color.Firebrick;
                    compatibility.Items.Add(item);
                }
                compatibilitySummary.Text = compatibilityReport.CanInstall
                    ? "检测通过；安装时还会运行真实 CUDA 与 OCR 验证。"
                    : compatibilityReport.HasFailures
                        ? "存在红色不兼容项目，已停止安装。"
                        : "GPU、驱动或计算能力无法确认；GPU-only 模式已停止安装。";
                compatibilitySummary.ForeColor = compatibilityReport.CanInstall
                    ? Color.DarkGreen
                    : compatibilityReport.HasFailures
                        ? Color.Firebrick
                        : Color.DarkOrange;
                install.Enabled = compatibilityReport.CanInstall;
            }
            catch (Exception error)
            {
                compatibilityReport = null;
                compatibility.Items.Clear();
                ListViewItem item = compatibility.Items.Add(
                    "⚠ 无法完成兼容性检测：" + error.Message);
                item.ForeColor = Color.DarkOrange;
                compatibilitySummary.Text = "请点击“重新检测”。";
                compatibilitySummary.ForeColor = Color.DarkOrange;
            }
            finally
            {
                progress.Style = ProgressBarStyle.Blocks;
                recheck.Enabled = true;
            }
        }

        private async void BeginInstall(object sender, EventArgs e)
        {
            if (compatibilityReport == null || !compatibilityReport.CanInstall)
            {
                MessageBox.Show(
                    "请先完成兼容性检测，并解决红色不兼容项目。",
                    "暂时不能安装",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning);
                return;
            }
            install.Enabled = false;
            recheck.Enabled = false;
            launch.Enabled = false;
            progress.Style = ProgressBarStyle.Marquee;
            try
            {
                string warning = await Task.Run(() =>
                    Install(
                        target,
                        true,
                        message => BeginInvoke((Action)(() => status.Text = message))));
                progress.Style = ProgressBarStyle.Blocks;
                progress.Value = 100;
                install.Text = "完成";
                if (launch.Checked)
                    Process.Start(Path.Combine(target, "RockKingdomShinyCounter.exe"));
                MessageBox.Show(
                    warning == null ? "安装完成。" : "安装完成。\r\n\r\n" + warning,
                    ProductName,
                    MessageBoxButtons.OK,
                    warning == null ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
                Close();
            }
            catch (Exception error)
            {
                progress.Style = ProgressBarStyle.Blocks;
                status.Text = "安装失败";
                install.Enabled = true;
                recheck.Enabled = true;
                launch.Enabled = true;
                MessageBox.Show(error.Message, "安装失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }
}
