$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$VerbosePreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Assert-PrivateItem($Item, $Sid, $Root) {
    if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'REPARSE_POINT' }
    $Acl = $Item.GetAccessControl()
    if ($Acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $Sid.Value) { throw 'OTHER_OWNER' }
    if ($Root -and -not $Acl.AreAccessRulesProtected) { throw 'INHERITED_ROOT_ACL' }
    $Rules = @($Acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if ($Rules.Count -eq 0) { throw 'EMPTY_ACL' }
    $Full = [Security.AccessControl.FileSystemRights]::FullControl
    foreach ($Rule in $Rules) {
        if ($Rule.IdentityReference.Value -ne $Sid.Value -or
            $Rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
            ($Rule.FileSystemRights -band $Full) -ne $Full) { throw 'OTHER_ACCESS' }
    }
    if ($Item -is [IO.DirectoryInfo]) {
        $Inherited = [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
        if (-not ($Rules | Where-Object { ($_.InheritanceFlags -band $Inherited) -eq $Inherited })) { throw 'NO_PRIVATE_INHERITANCE' }
        foreach ($Child in $Item.GetFileSystemInfos()) { Assert-PrivateItem $Child $Sid $false }
    }
}

try {
    $Mandatory = Get-ExecutionPolicy -List | Where-Object { $_.Scope -in @('MachinePolicy', 'UserPolicy') -and $_.ExecutionPolicy -eq 'Restricted' }
    if ((Get-ExecutionPolicy) -eq 'AllSigned' -or $Mandatory) { throw 'POLICY_REQUIRES_APPROVED_ROUTE' }
    $Request = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ReportKitInput)) | ConvertFrom-Json
    if ($Request.action -eq 'prepare' -or $Request.action -eq 'check') {
        $Sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
        if ($Request.action -eq 'prepare' -and -not [IO.Directory]::Exists($Request.path)) {
            if ([IO.File]::Exists($Request.path)) { throw 'NOT_A_DIRECTORY' }
            $Acl = New-Object Security.AccessControl.DirectorySecurity
            $Acl.SetOwner($Sid)
            $Acl.SetAccessRuleProtection($true, $false)
            $Rule = New-Object Security.AccessControl.FileSystemAccessRule(
                $Sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
            $Acl.AddAccessRule($Rule)
            [void][IO.Directory]::CreateDirectory($Request.path, $Acl)
        }
        $Item = Get-Item -LiteralPath $Request.path -Force
        Assert-PrivateItem $Item $Sid ($Request.action -eq 'prepare')
        [Console]::Write('RK_PRIVATE_OK')
    } elseif ($Request.action -eq 'credential') {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class ReportKitLiveDuneCredential {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    private struct Credential {
        public uint Flags, Type;
        public IntPtr TargetName, Comment;
        public long LastWritten;
        public uint BlobSize;
        public IntPtr Blob;
        public uint Persist, AttributeCount;
        public IntPtr Attributes, TargetAlias, UserName;
    }
    [DllImport("advapi32.dll", EntryPoint="CredReadW", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool Read(string target, uint type, uint flags, out IntPtr value);
    [DllImport("advapi32.dll", ExactSpelling=true)]
    private static extern void CredFree(IntPtr value);
    public static string ReadEncoded(string target) {
        IntPtr pointer;
        if (!Read(target, 1, 0, out pointer)) throw new InvalidOperationException("CREDENTIAL_UNAVAILABLE");
        byte[] blob = null, utf8 = null;
        try {
            Credential credential = (Credential)Marshal.PtrToStructure(pointer, typeof(Credential));
            if (credential.Type != 1 || credential.Blob == IntPtr.Zero || credential.BlobSize == 0 ||
                credential.BlobSize > 2560 || credential.BlobSize % 2 != 0) throw new InvalidOperationException("CREDENTIAL_INVALID");
            blob = new byte[credential.BlobSize];
            Marshal.Copy(credential.Blob, blob, 0, blob.Length);
            utf8 = Encoding.UTF8.GetBytes(new UnicodeEncoding(false, false, true).GetString(blob).TrimEnd('\0'));
            return Convert.ToBase64String(utf8);
        } finally {
            if (blob != null) Array.Clear(blob, 0, blob.Length);
            if (utf8 != null) Array.Clear(utf8, 0, utf8.Length);
            CredFree(pointer);
        }
    }
}
'@
        [Console]::Write('RK_CREDENTIAL:' + [ReportKitLiveDuneCredential]::ReadEncoded($Request.target))
    } else { throw 'ACTION_INVALID' }
} catch {
    [Console]::Error.WriteLine('LIVEDUNE_WINDOWS_ACCESS_STOPPED')
    exit 1
}
