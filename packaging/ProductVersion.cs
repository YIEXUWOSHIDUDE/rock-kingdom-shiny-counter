using System;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;

internal static class ProductVersion
{
    private const string ResourceName = "RockKingdomShinyCounter.VERSION";

    internal static readonly string Current = Load();

    private static string Load()
    {
        Assembly assembly = Assembly.GetExecutingAssembly();
        using (Stream stream = assembly.GetManifestResourceStream(ResourceName))
        {
            if (stream == null)
                throw new InvalidDataException("安装程序缺少嵌入的 VERSION 资源。");
            using (StreamReader reader = new StreamReader(stream))
            {
                string version = reader.ReadToEnd().Trim();
                if (!Regex.IsMatch(version, @"^\d+\.\d+\.\d+$"))
                    throw new InvalidDataException("VERSION 格式无效：" + version);
                return version;
            }
        }
    }
}
