from pathlib import Path

import paramiko


def _load_config(ssh_conf_file="~/.ssh/config"):
    config = paramiko.SSHConfig()
    with Path(ssh_conf_file).expanduser().open() as f:
        config.parse(f)
    return config


def get_hosts(ssh_conf_file="~/.ssh/config"):
    """Gibt alle explizit definierten Hosts zurück (ohne Wildcard-Patterns)"""
    config = _load_config(ssh_conf_file)
    return sorted(h for h in config.get_hostnames() if "*" not in h and "?" not in h)


def get_data_for_host(ssh_conf_file="~/.ssh/config", host="localhost"):
    config = _load_config(ssh_conf_file)
    data = config.lookup(host)

    # sshconf gab identityfile als String zurück, paramiko als Liste
    identityfile = data.get("identityfile")
    if isinstance(identityfile, list):
        data["identityfile"] = identityfile[0] if identityfile else None

    return data


if __name__ == "__main__":
    print("ssh config kram")
    print(get_data_for_host(host="samson"))
