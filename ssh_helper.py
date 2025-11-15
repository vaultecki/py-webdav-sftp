from sshconf import read_ssh_config, empty_ssh_config_file
from os.path import expanduser


def get_data_for_host(ssh_conf_file="~/.ssh/config", host="localhost"):
    c = read_ssh_config(expanduser(ssh_conf_file))
    return c.host(host)


if __name__ == "__main__":
    print("ssh config kram")
    print(get_data_for_host(host="samson"))
