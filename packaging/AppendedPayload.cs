using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;

internal static class AppendedPayload
{
    private static readonly byte[] FooterMagic = Encoding.ASCII.GetBytes("RKSCZIP1");

    internal static void Extract(string executablePath, string destination)
    {
        Directory.CreateDirectory(destination);
        string root = Path.GetFullPath(destination)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        using (Stream payload = OpenRead(executablePath))
        using (ZipArchive archive = new ZipArchive(payload, ZipArchiveMode.Read, false))
        {
            foreach (ZipArchiveEntry entry in archive.Entries)
            {
                string relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                string outputPath = Path.GetFullPath(Path.Combine(destination, relative));
                if (!outputPath.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("安装包包含越界路径：" + entry.FullName);
                if (entry.FullName.EndsWith("/", StringComparison.Ordinal))
                {
                    Directory.CreateDirectory(outputPath);
                    continue;
                }
                string parent = Path.GetDirectoryName(outputPath);
                if (!string.IsNullOrEmpty(parent))
                    Directory.CreateDirectory(parent);
                using (Stream source = entry.Open())
                using (FileStream output = File.Create(outputPath))
                    source.CopyTo(output);
            }
        }
    }

    internal static Stream OpenRead(string executablePath)
    {
        FileStream source = File.OpenRead(executablePath);
        try
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
            return new SegmentReadStream(source, payloadOffset, payloadLength);
        }
        catch
        {
            source.Dispose();
            throw;
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

    private sealed class SegmentReadStream : Stream
    {
        private readonly Stream source;
        private readonly long start;
        private readonly long length;
        private long position;

        internal SegmentReadStream(Stream source, long start, long length)
        {
            this.source = source;
            this.start = start;
            this.length = length;
        }

        public override bool CanRead { get { return true; } }
        public override bool CanSeek { get { return true; } }
        public override bool CanWrite { get { return false; } }
        public override long Length { get { return length; } }
        public override long Position
        {
            get { return position; }
            set { Seek(value, SeekOrigin.Begin); }
        }

        public override int Read(byte[] buffer, int offset, int count)
        {
            long remaining = length - position;
            if (remaining <= 0)
                return 0;
            int requested = (int)Math.Min(count, remaining);
            source.Position = start + position;
            int read = source.Read(buffer, offset, requested);
            position += read;
            return read;
        }

        public override long Seek(long offset, SeekOrigin origin)
        {
            long next;
            if (origin == SeekOrigin.Begin)
                next = offset;
            else if (origin == SeekOrigin.Current)
                next = position + offset;
            else if (origin == SeekOrigin.End)
                next = length + offset;
            else
                throw new ArgumentOutOfRangeException("origin");
            if (next < 0 || next > length)
                throw new IOException("尝试读取安装包载荷范围之外的数据。");
            position = next;
            return position;
        }

        public override void Flush()
        {
        }

        public override void SetLength(long value)
        {
            throw new NotSupportedException();
        }

        public override void Write(byte[] buffer, int offset, int count)
        {
            throw new NotSupportedException();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
                source.Dispose();
            base.Dispose(disposing);
        }
    }
}
