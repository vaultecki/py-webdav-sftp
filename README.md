# PyDAVSFTP - WebDAV SFTP Bridge

A Python-based WebDAV server that bridges remote SFTP filesystems, allowing you to access and manage files on remote SSH servers through the WebDAV protocol. Perfect for integrating legacy systems with modern file management tools.

## Features

- **WebDAV Protocol Support**: Access remote files through any WebDAV-compatible client
- **SFTP Backend**: Connect to any SSH/SFTP server using standard SSH configuration
- **Connection Pooling**: Thread-safe connection management for optimal performance
- **GUI Application**: User-friendly interface built with Tkinter
- **Command-Line Interface**: Full CLI for scripting, headless servers, or scheduled/autostart deployments
- **Windows Drive Mounting**: Optionally auto-mount the WebDAV share as a drive letter (e.g. `X:`) on start
- **Configuration Persistence**: Save and restore your settings
- **Autostart Support**: Launch the server automatically on application start
- **Real-time Logging**: Monitor server activity and troubleshoot issues
- **File Operations**: Full support for create, read, update, delete, move, and copy operations

## Requirements

- Python 3.8 or higher
- SSH key-based authentication configured
- Basic understanding of SSH configuration

## Installation

1. Clone or download this repository:
```bash
git clone <repository-url>
cd PyDAVSFTP
```

2. Install dependencies:
```bash
pip install .
```

3. Verify your SSH configuration:
```bash
# Ensure your SSH keys are in place
ls -la ~/.ssh/config
ls -la ~/.ssh/id_rsa  # or your key file
```

## Quick Start

### GUI Mode (Recommended)

1. Run the application:
```bash
python main.py
```

2. Configure your connection:
   - **SSH Config File**: Path to your SSH configuration (default: `~/.ssh/config`)
   - **Host**: Select a host from your SSH config
   - **Remote Path**: The directory to expose via WebDAV (default: `/tmp`)
   - **Pool Size**: Number of SFTP connections (default: 3)
   - **WebDAV Port**: Listen port (default: 8080)

3. Click "Start" to launch the server

4. Access your files via WebDAV:
   - URL: `http://localhost:8080`
   - Use any WebDAV client (Windows File Explorer, macOS Finder, etc.)

### Command-Line Mode

For scripting, headless servers, or scheduled/autostart deployments (no GUI needed), use `cli.py`:

```bash
python cli.py --host myserver
```

`--host` is the only required argument (a host name from your SSH config). All other options have sensible defaults:

```bash
python cli.py \
  --host myserver \
  --ssh-config ~/.ssh/config \
  --remote-path /home/user/files \
  --port 8080 \
  --pool-size 3 \
  --connection-timeout 10 \
  --drive-letter X \
  --log-level INFO
```

Run `python cli.py --help` for the full list of options. Stop the server with `Ctrl+C` (or `SIGTERM`, e.g. from a service manager) - the connection pool and, if used, the mounted drive letter are cleaned up automatically.

## Configuration

### SSH Configuration Setup

Ensure your `~/.ssh/config` file includes your remote host:

```
Host myserver
    HostName example.com
    User myusername
    IdentityFile ~/.ssh/id_rsa
    Port 22
```

### Application Settings

**SSH Configuration**:
- Path to your SSH config file
- Host selection from available SSH hosts
- Remote path to expose

**WebDAV Server**:
- Custom port (1024-65535)

**Connection Pool**:
- Pool size (1-10 connections)
- Higher values support more concurrent operations

**Autostart**:
- Enable automatic server startup
- Server and UI minimize on launch

## Usage

### From GUI

The GUI provides intuitive controls for all operations:
- Start/Stop the server with a single button
- Browse and select SSH hosts
- Monitor server status and logs in real-time
- Save configuration for future sessions

### From WebDAV Clients

Once the server is running, connect using any WebDAV client:

**Windows File Explorer (automatic)**:

If a drive letter is configured (GUI: "Laufwerk (Windows)" dropdown, CLI: `--drive-letter X`), the server mounts itself as that drive right after starting, and unmounts it again when stopped - no manual steps needed. This runs `net use X: \\localhost@8080\DavWWWRoot /persistent:no` under the hood via the Windows WebDAV redirector (`WebClient` service). If it fails (drive letter already in use, `WebClient` service unavailable), the server keeps running regardless - check the log for details and mount manually as a fallback.

> **Known Windows limitation**: The `WebClient` redirector has a default transfer size limit of **50 MB per file** (`FileSizeLimitInBytes` under `HKLM\SYSTEM\CurrentControlSet\Services\WebClient\Parameters`). Larger files will fail to copy through the mounted drive until this registry value is raised (and the `WebClient` service restarted). This is a Windows-side limitation, unrelated to this tool's connection pool or port.

**Windows File Explorer (manual)**:
1. Open File Explorer → Computer → Map Network Drive
2. Enter: `\\localhost@8080\DavWWWRoot`

**macOS Finder**:
1. Go → Connect to Server
2. Enter: `http://localhost:8080`

**Linux (Nautilus/Dolphin)**:
1. Enter location: `dav://localhost:8080`

**Third-party Applications**:
- Any application supporting WebDAV (OnlyOffice, LibreOffice, etc.)

## Architecture

### Connection Pool

The application maintains a pool of persistent SFTP connections:
- Pre-initialized connections reduce latency
- Thread-safe resource management
- Automatic connection recovery
- Keepalive monitoring prevents timeout

### WebDAV Provider

Maps WebDAV operations to SFTP filesystem operations:
- `GET` → Read files
- `PUT` → Write files
- `PROPFIND` → List directories
- `DELETE` → Remove files/folders
- `MOVE` → Rename or move
- `COPY` → Duplicate files/folders
- `MKCOL` → Create directories

### GUI Components

Built with Tkinter for cross-platform compatibility:
- Status monitoring
- SSH configuration management
- Real-time logging
- Configuration persistence

## Troubleshooting

### Connection Errors

**Error: "SSH Config could not be loaded"**
- Verify SSH config file exists: `~/.ssh/config`
- Check file permissions: `chmod 600 ~/.ssh/config`
- Ensure format is correct (no trailing spaces)

**Error: "Remote path not found"**
- Verify the path exists on the remote server: `ssh user@host "ls -la /path"`
- Ensure user has read/write permissions

**Error: "Pool timeout - all connections busy"**
- Increase pool size in settings
- Reduce concurrent WebDAV operations
- Check if remote server has connection limits

### Authentication Issues

**Error: "Permission denied (publickey)"**
- Verify SSH key permissions: `chmod 600 ~/.ssh/id_rsa`
- Test SSH connection: `ssh -i ~/.ssh/id_rsa user@host`
- Check SSH agent: `ssh-add ~/.ssh/id_rsa`

### Performance Issues

**Slow file transfers**:
- Compression is enabled by default (helps with network latency)
- Reduce pool size if memory is limited
- Check remote server load and network connectivity

**Frequent connection timeouts**:
- Increase `connection_timeout` in `SFTPConfig`
- Verify network stability
- Check firewall rules

### Windows Auto-Mount Issues

**Drive letter doesn't mount / `net use` fails**:
- Check the log for the exact `net use` error message
- Make sure the drive letter isn't already in use (`net use` with no arguments lists current mappings)
- Ensure the `WebClient` service is available (it's part of Windows client editions; not installed by default on some Windows Server editions)
- Try the manual mapping command from the log/README to see the raw error
- **Mount times out on the very first attempt after a fresh boot/login**: the `WebClient` service starts as "Manual (Trigger Start)" and its cold start can take longer than the mount timeout. The server starts it explicitly before mounting and waits up to 30s for `net use` to finish; if it still times out, try starting the server again (the service will then already be running and the second mount should be fast), or set `WebClient` to Automatic startup (`services.msc`) to avoid the cold start entirely.

**Files over 50 MB fail to copy through the mounted drive**:
- This is the `WebClient` redirector's default transfer limit, not a limit of this tool
- Raise `FileSizeLimitInBytes` (DWORD, bytes) under `HKLM\SYSTEM\CurrentControlSet\Services\WebClient\Parameters` and restart the `WebClient` service

## Configuration Files

- **Config Location**: 
  - Windows: `%APPDATA%\Local\ThaDAVSFTP\ThaDAVSFTP.config`
  - Linux/macOS: `~/.config/ThaDAVSFTP/ThaDAVSFTP.config`

- **Format**: JSON

Example configuration:
```json
{
    "ssh_config_file": "~/.ssh/config",
    "host": "myserver",
    "remote_path": "/home/user/files",
    "pool_size": 3,
    "webdav_port": 8080,
    "drive_letter": "X",
    "autostart": false
}
```

`drive_letter` is optional and Windows-only; leave it empty (`""`) to disable auto-mounting.

## Security Considerations

- **No authentication**: By default, WebDAV access is unrestricted (local connections only)
- **SSH key-based auth**: Relies on SSH key authentication for remote access
- **Known hosts verification**: Validates remote server identity using `~/.ssh/known_hosts`
- **Local binding**: Server binds to localhost only (not accessible from network)

For production use:
- Restrict network access via firewall
- Consider implementing WebDAV authentication
- Use VPN for remote access
- Keep SSH keys secure and backed up

## Dependencies

- **paramiko**: SSH protocol implementation (also used to parse `~/.ssh/config`)
- **WsgiDAV**: WebDAV server framework
- **cheroot**: WSGI HTTP server
- **tkinter**: GUI (usually included with Python)

See `pyproject.toml` for exact versions, or install the `dev` extra to additionally get `pytest`, `ruff`, and `mypy` for development.

## Advanced Usage

### Custom SFTP Configuration

For CLI/scripted usage, all connection settings are exposed as `cli.py` arguments (see [Command-Line Mode](#command-line-mode)) - no source editing required.

To embed the server in your own Python code instead, construct `SFTPConfig` directly:

```python
from webdav_sftp import SFTPConfig, SFTPProvider

config = SFTPConfig(
    host="example.com",
    user="username",
    keyfile="/path/to/key",
    remote_path="/var/data",
    port=2222,
    pool_size=5,
    connection_timeout=15
)
provider = SFTPProvider(config)
```

### Logging

- **GUI**: Adjust the level in `main.py`'s `logging.basicConfig(level=logging.INFO, ...)` call.
- **CLI**: Use `--log-level DEBUG` (or `WARNING`/`ERROR`) - no source editing needed.

## Development

Install dev dependencies and run the test suite:

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy .
```

Git hooks (ruff + mypy on commit, pytest on push) einrichten:

```bash
pre-commit install --hook-type pre-commit --hook-type pre-push
```

## License

[Apache 2.0]

## Contributing

Contributions are welcome! Please submit issues and pull requests.

## Support

For issues, questions, or suggestions, please open an issue on the project repository.

