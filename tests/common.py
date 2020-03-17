import subprocess


def install_rpm():
    subprocess.check_call("rpm -i /scalyr-agent.rpm", shell=True, stdin=subprocess.PIPE)


def install_deb():
    subprocess.check_call("dpkg -i /scalyr-agent.deb", shell=True, stdin=subprocess.PIPE)