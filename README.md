# ThaDAVSFTP - WebDAV SFTP Bridge

A Python-based WebDAV server that bridges remote SFTP filesystems, allowing you to access and manage files on remote SSH servers through the WebDAV protocol. Perfect for integrating legacy systems with modern file management tools.

## Features

- **WebDAV Protocol Support**: Access remote files through any WebDAV-compatible client
- **SFTP Backend**: Connect to any SSH/SFTP server using standard SSH configuration
- **Connection Pooling**: Thread-safe connection management for optimal performance
- **GUI Application**: User-friendly interface built with Tkinter
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
cd ThaDAVSFTP
```

2. Install dependencies:
```bash
pip install -r requirements.txt
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

For scripting or server deployments, use the standalone provider:

```bash
python webdav_sftp.py
```

Edit the `__main__` section in `webdav_sftp.py` to configure your SFTP connection.

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

**Windows File Explorer**:
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
    "autostart": false
}
```

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

- **paramiko**: SSH protocol implementation
- **WsgiDAV**: WebDAV server framework
- **cheroot**: WSGI HTTP server
- **sshconf**: SSH configuration parser
- **tkinter**: GUI (usually included with Python)

See `requirements.txt` for exact versions.

## Advanced Usage

### Custom SFTP Configuration

Edit `webdav_sftp.py` to use different configurations:

```python
config = SFTPConfig(
    host="example.com",
    user="username",
    keyfile="/path/to/key",
    remote_path="/var/data",
    port=2222,
    pool_size=5,
    connection_timeout=15
)
```

### Logging

Adjust logging level in `main.py`:

```python
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG for verbose output
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### Running as Service (Linux)

Create a systemd service file for automatic startup:

```ini
[Unit]
Description=ThaDAVSFTP WebDAV SFTP Bridge
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/ThaDAVSFTP
ExecStart=/usr/bin/python3 /path/to/ThaDAVSFTP/main.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## License

[Specify your license here - e.g., MIT, GPL, etc.]

## Contributing

Contributions are welcome! Please submit issues and pull requests.

## Support

For issues, questions, or suggestions, please open an issue on the project repository.

