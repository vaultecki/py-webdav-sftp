import textwrap

import ssh_helper


def test_get_hosts_excludes_wildcards(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text(textwrap.dedent("""\
        Host myserver
            HostName example.com
            User bob

        Host *
            Compression yes
    """))

    hosts = ssh_helper.get_hosts(str(config_path))
    assert hosts == ["myserver"]


def test_get_data_for_host_resolves_fields(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text(textwrap.dedent("""\
        Host myserver
            HostName example.com
            User bob
            Port 2222
            IdentityFile ~/.ssh/id_bob
    """))

    data = ssh_helper.get_data_for_host(str(config_path), host="myserver")
    assert data["hostname"] == "example.com"
    assert data["user"] == "bob"
    assert data["port"] == "2222"
    assert data["identityfile"].endswith("id_bob")
    assert isinstance(data["identityfile"], str)  # nicht die paramiko-Liste
