using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Web.Script.Serialization;

internal sealed class PayloadManifestDocument
{
    public List<PayloadManifestEntry> files { get; set; }
}

internal sealed class PayloadManifestEntry
{
    public string path { get; set; }
    public long bytes { get; set; }
    public string sha256 { get; set; }
}

internal static class PayloadManifestValidator
{
    internal static void Validate(string root)
    {
        string manifestPath = Path.Combine(root, "MANIFEST.sha256.json");
        if (!File.Exists(manifestPath))
            throw new InvalidDataException("安装包缺少文件完整性清单。");

        PayloadManifestDocument manifest;
        try
        {
            JavaScriptSerializer serializer = new JavaScriptSerializer();
            manifest = serializer.Deserialize<PayloadManifestDocument>(
                File.ReadAllText(manifestPath));
        }
        catch (Exception error)
        {
            throw new InvalidDataException("安装包文件完整性清单无效。", error);
        }
        if (manifest == null || manifest.files == null || manifest.files.Count == 0)
            throw new InvalidDataException("安装包文件完整性清单为空。");

        string normalizedRoot = Path.GetFullPath(root)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        HashSet<string> expectedPaths = new HashSet<string>(
            StringComparer.OrdinalIgnoreCase);
        foreach (PayloadManifestEntry entry in manifest.files)
        {
            if (entry == null || string.IsNullOrWhiteSpace(entry.path))
                throw new InvalidDataException("安装包文件完整性清单包含空路径。");
            string relative = entry.path.Replace('/', Path.DirectorySeparatorChar);
            string normalizedRelative = relative.Replace(
                Path.DirectorySeparatorChar,
                '/');
            if (!expectedPaths.Add(normalizedRelative))
                throw new InvalidDataException(
                    "安装包文件完整性清单包含重复路径：" + entry.path);
            string fullPath = Path.GetFullPath(Path.Combine(root, relative));
            if (!fullPath.StartsWith(normalizedRoot, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("安装包文件完整性清单包含越界路径。");
            if (!File.Exists(fullPath))
                throw new InvalidDataException("安装包缺少文件：" + entry.path);
            FileInfo file = new FileInfo(fullPath);
            if (file.Length != entry.bytes)
                throw new InvalidDataException("安装包文件长度校验失败：" + entry.path);
            using (SHA256 sha = SHA256.Create())
            using (FileStream input = File.OpenRead(fullPath))
            {
                string actual = BitConverter.ToString(sha.ComputeHash(input))
                    .Replace("-", "")
                    .ToLowerInvariant();
                if (!string.Equals(actual, entry.sha256, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("安装包文件哈希校验失败：" + entry.path);
            }
        }

        HashSet<string> actualPaths = new HashSet<string>(
            StringComparer.OrdinalIgnoreCase);
        foreach (string file in Directory.GetFiles(
            root,
            "*",
            SearchOption.AllDirectories))
        {
            string fullPath = Path.GetFullPath(file);
            if (string.Equals(
                fullPath,
                Path.GetFullPath(manifestPath),
                StringComparison.OrdinalIgnoreCase))
                continue;
            if (!fullPath.StartsWith(normalizedRoot, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("安装包包含越界文件。");
            actualPaths.Add(
                fullPath.Substring(normalizedRoot.Length).Replace('\\', '/'));
        }
        if (!actualPaths.SetEquals(expectedPaths))
            throw new InvalidDataException("安装包文件集合与完整性清单不一致。");
    }
}
